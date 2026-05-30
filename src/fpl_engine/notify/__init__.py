"""Notification service: Pushover + email, per-channel/per-type thresholds (Phase 9)."""

from .service import Channel, EmailChannel, NotificationService, PushoverChannel

__all__ = ["Channel", "EmailChannel", "NotificationService", "PushoverChannel"]
