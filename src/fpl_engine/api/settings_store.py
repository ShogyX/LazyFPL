"""Runtime app settings + secrets backing the UI Settings page (plan 10.2 / F1).

General config (entry id, horizon, theme, model selection, planner knobs and
notification toggles) is stored as JSONB in ``core.app_settings`` and is freely
readable. Secrets (cookies / API keys / SMTP + Pushover credentials) live in the
same table flagged ``is_secret`` and are NEVER returned in plaintext — the API
returns only a masked presence flag. Stored secrets override env/.env at read
time via :func:`effective_secret`, so the operator can manage everything from
the UI without touching the host.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from ..config import get_settings
from ..db.engine import get_sessionmaker
from ..db.models import app_settings

# Non-secret config keys the UI can edit, with safe defaults. Anything not here
# is rejected by the writer so the table can't be used as an arbitrary KV dump.
GENERAL_DEFAULTS: dict[str, Any] = {
    "entry_id": None,
    "season": None,
    "horizon": 6,
    "theme": "light",          # light | dark
    "active_model": "v1",      # serving model_version used for /predictions etc.
    "active_strategy": "ict",  # ensemble/predictor strategy surfaced as default
    "ft_value": 1.5,
    "decay_base": 0.84,
    "eo_weight": 0.0,
    "notify_email": False,
    "notify_push": False,
    "ev_threshold": 1.0,
    # Email (SMTP) delivery — host/port/sender/recipient. Credentials live in
    # SECRET_KEYS. A recipient (smtp_to) is required for email to send.
    "smtp_host": None,
    "smtp_port": 587,
    "smtp_from": None,
    "smtp_to": None,
}

# Secret keys editable from the UI. Maps the settings key -> the env-backed
# attribute on ``Settings`` so stored values transparently override env.
SECRET_KEYS: dict[str, str] = {
    "fpl_session_cookie": "fpl_session_cookie",
    "api_football_key": "api_football_key",
    "sharpapi_key": "sharpapi_key",
    "sgo_key": "sgo_key",
    "oddspapi_key": "oddspapi_key",
    "oddsapi_io_key": "oddsapi_io_key",
    "betfair_app_key": "betfair_app_key",
    "betfair_username": "betfair_username",
    "betfair_password": "betfair_password",
    "pushover_token": "pushover_token",
    "pushover_user": "pushover_user",
    "smtp_username": "smtp_username",
    "smtp_password": "smtp_password",
}


def _sm():
    return get_sessionmaker()


def read_general() -> dict[str, Any]:
    """Merge stored non-secret config over the defaults."""
    out = dict(GENERAL_DEFAULTS)
    with _sm()() as s:
        rows = s.execute(
            select(app_settings.c.key, app_settings.c.value)
            .where(app_settings.c.is_secret.is_(False))
        ).all()
    for r in rows:
        out[r.key] = r.value
    return out


def write_general(updates: dict[str, Any]) -> dict[str, Any]:
    """Upsert recognised non-secret keys; ignore unknowns. Returns merged view."""
    known = {k: v for k, v in updates.items() if k in GENERAL_DEFAULTS}
    if known:
        with _sm()() as s:
            for k, v in known.items():
                stmt = insert(app_settings).values(key=k, value=v, is_secret=False)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[app_settings.c.key],
                    set_={"value": v, "updated_at": func.now()},
                )
                s.execute(stmt)
            s.commit()
    return read_general()


def secret_presence() -> dict[str, bool]:
    """Masked status of every editable secret: stored-in-DB OR present in env."""
    settings = get_settings()
    with _sm()() as s:
        stored = {
            r.key for r in s.execute(
                select(app_settings.c.key).where(app_settings.c.is_secret.is_(True))
            ).all()
        }
    out: dict[str, bool] = {}
    for key, env_attr in SECRET_KEYS.items():
        env_val = getattr(settings, env_attr, None)
        has_env = bool(env_val.get_secret_value()) if env_val is not None else False
        out[key] = key in stored or has_env
    return out


def write_secrets(updates: dict[str, str | None]) -> dict[str, bool]:
    """Set or clear secret keys. A ``None``/empty value clears the stored secret
    (env fallback may still apply). Unknown keys are ignored."""
    with _sm()() as s:
        for key, val in updates.items():
            if key not in SECRET_KEYS:
                continue
            if val:
                stmt = insert(app_settings).values(key=key, value=val, is_secret=True)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[app_settings.c.key],
                    set_={"value": val, "is_secret": True, "updated_at": func.now()},
                )
                s.execute(stmt)
            else:
                s.execute(delete(app_settings).where(app_settings.c.key == key))
        s.commit()
    return secret_presence()


def effective_secret(key: str) -> str | None:
    """Resolve a secret's plaintext: DB-stored value wins, else env/.env.

    Server-side only — never expose the return value over the API.
    """
    if key not in SECRET_KEYS:
        return None
    with _sm()() as s:
        row = s.execute(
            select(app_settings.c.value)
            .where(app_settings.c.key == key, app_settings.c.is_secret.is_(True))
        ).first()
    if row and row.value:
        return str(row.value)
    env_val = getattr(get_settings(), SECRET_KEYS[key], None)
    return env_val.get_secret_value() if env_val is not None else None
