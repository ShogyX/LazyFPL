"""Notification service (plan 9.4): Pushover + email, both active by default.

Notifications fire only when a recommendation clears EV and confidence
thresholds (per-type). Pushover carries a concise action; email carries fuller
rationale. Transports are injectable so tests never hit the network/SMTP, and
secrets are read from settings via ``SecretStr`` (never logged).
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable, Protocol

import httpx

from ..config import Settings, get_settings
from ..logging_setup import get_logger

log = get_logger(__name__)


class Channel(Protocol):
    name: str
    enabled: bool

    def send(self, subject: str, body: str, detail: str | None = None) -> bool: ...


class PushoverChannel:
    name = "pushover"

    def __init__(self, token: str | None, user: str | None,
                 client: httpx.Client | None = None):
        self._token = token
        self._user = user
        self._client = client or httpx.Client(timeout=10.0)
        self.enabled = bool(token and user)

    def send(self, subject: str, body: str, detail: str | None = None) -> bool:
        if not self.enabled:
            return False
        resp = self._client.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": self._token, "user": self._user,
                  "title": subject, "message": body},
        )
        ok = resp.status_code < 300
        if not ok:
            log.warning("pushover send failed", extra={"status": resp.status_code})
        return ok


class EmailChannel:
    name = "email"

    def __init__(self, host: str | None, port: int, username: str | None,
                 password: str | None, sender: str | None, recipient: str | None,
                 smtp_factory: Callable[..., object] | None = None):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._recipient = recipient
        self._smtp_factory = smtp_factory
        self.enabled = bool(host and sender and recipient)

    def send(self, subject: str, body: str, detail: str | None = None) -> bool:
        if not self.enabled:
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._sender
        msg["To"] = self._recipient
        msg.set_content(detail or body)
        factory = self._smtp_factory
        if factory is None:  # pragma: no cover - real SMTP not exercised in tests
            import smtplib
            factory = lambda: smtplib.SMTP(self._host, self._port)
        client = factory()
        try:
            if self._username and self._password:
                client.login(self._username, self._password)
            client.send_message(msg)
        finally:
            close = getattr(client, "quit", None) or getattr(client, "close", None)
            if close:
                close()
        return True


@dataclass
class NotificationService:
    channels: list[Channel]
    ev_threshold: float = 1.0
    confidence_threshold: float = 0.0

    def notify(self, kind: str, subject: str, body: str, *, ev: float,
               confidence: float, detail: str | None = None) -> list[str]:
        """Dispatch to all enabled channels iff thresholds are cleared.

        Returns the names of channels that accepted the message ([] = silent).
        """
        if ev < self.ev_threshold or confidence < self.confidence_threshold:
            log.info("notification suppressed (below threshold)",
                     extra={"kind": kind, "ev": ev, "confidence": confidence})
            return []
        delivered: list[str] = []
        for ch in self.channels:
            if not ch.enabled:
                continue
            try:  # one channel's failure must not abort the others
                if ch.send(subject, body, detail):
                    delivered.append(ch.name)
            except Exception as exc:
                log.warning("channel send failed",
                            extra={"channel": ch.name, "error": str(exc)})
        log.info("notification dispatched", extra={"kind": kind, "channels": delivered})
        return delivered

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **kw) -> "NotificationService":
        s = settings or get_settings()

        def secret(v):
            return v.get_secret_value() if v is not None else None

        # Operator-editable values from the Settings page (DB) override env: the
        # SMTP host/port/sender/recipient and the credentials. Lazy import keeps
        # the notify module free of an api-package import cycle.
        general: dict = {}
        eff = None
        try:
            from ..api import settings_store
            general = settings_store.read_general()
            eff = settings_store.effective_secret
        except Exception:
            pass

        def gen(key, fallback):
            v = general.get(key)
            return v if v not in (None, "") else fallback

        def cred(key, env_val):
            return eff(key) if eff is not None else secret(env_val)

        channels: list[Channel] = [
            PushoverChannel(cred("pushover_token", s.pushover_token),
                            cred("pushover_user", s.pushover_user)),
            EmailChannel(gen("smtp_host", s.smtp_host), int(gen("smtp_port", s.smtp_port)),
                         cred("smtp_username", s.smtp_username),
                         cred("smtp_password", s.smtp_password),
                         gen("smtp_from", s.smtp_from), gen("smtp_to", s.smtp_to)),
        ]
        return cls(channels=channels, **kw)
