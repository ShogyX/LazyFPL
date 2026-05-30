"""Notification service: threshold gating + channel enable (no network/SMTP)."""

from fpl_engine.config import Settings
from fpl_engine.notify import EmailChannel, NotificationService, PushoverChannel


class FakeChannel:
    def __init__(self, name, enabled=True):
        self.name = name
        self.enabled = enabled
        self.sent = []

    def send(self, subject, body, detail=None):
        self.sent.append((subject, body, detail))
        return True


def test_above_threshold_delivers_on_all_channels():
    a, b = FakeChannel("a"), FakeChannel("b")
    svc = NotificationService([a, b], ev_threshold=1.0, confidence_threshold=0.2)
    delivered = svc.notify("transfer", "subj", "body", ev=5.0, confidence=0.5)
    assert set(delivered) == {"a", "b"}
    assert len(a.sent) == 1 and len(b.sent) == 1


def test_below_ev_threshold_is_silent():
    a, b = FakeChannel("a"), FakeChannel("b")
    svc = NotificationService([a, b], ev_threshold=1.0)
    assert svc.notify("transfer", "s", "b", ev=0.5, confidence=1.0) == []
    assert a.sent == [] and b.sent == []


def test_below_confidence_threshold_is_silent():
    a = FakeChannel("a")
    svc = NotificationService([a], ev_threshold=0.0, confidence_threshold=0.5)
    assert svc.notify("captain", "s", "b", ev=10.0, confidence=0.1) == []
    assert a.sent == []


def test_disabled_channel_skipped():
    on, off = FakeChannel("on"), FakeChannel("off", enabled=False)
    svc = NotificationService([on, off], ev_threshold=0.0)
    delivered = svc.notify("transfer", "s", "b", ev=1.0, confidence=1.0)
    assert delivered == ["on"]
    assert off.sent == []


def test_one_channel_failure_does_not_abort_others():
    class BoomChannel:
        name = "boom"
        enabled = True

        def send(self, *a, **k):
            raise RuntimeError("smtp down")

    boom, ok = BoomChannel(), FakeChannel("ok")
    svc = NotificationService([boom, ok], ev_threshold=0.0)
    delivered = svc.notify("transfer", "s", "b", ev=5.0, confidence=1.0)
    assert delivered == ["ok"]          # boom failed, ok still delivered
    assert len(ok.sent) == 1


def test_channels_disabled_without_credentials():
    assert PushoverChannel(None, None).enabled is False
    assert EmailChannel(None, 587, None, None, None, None).enabled is False
    # from_settings with empty settings -> all channels present but disabled
    svc = NotificationService.from_settings(Settings(_env_file=None))
    assert all(not ch.enabled for ch in svc.channels)
    assert {ch.name for ch in svc.channels} == {"pushover", "email"}


def test_email_channel_uses_injected_smtp():
    sent = {}

    class FakeSMTP:
        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, msg):
            sent["msg"] = msg

        def quit(self):
            sent["quit"] = True

    ch = EmailChannel("smtp.example.com", 587, "user", "pw", "from@x.com", "to@x.com",
                      smtp_factory=lambda: FakeSMTP())
    assert ch.enabled
    assert ch.send("subj", "short", detail="full detail") is True
    assert sent["msg"]["To"] == "to@x.com"
    assert "full detail" in sent["msg"].get_content()
    assert sent["quit"] is True
