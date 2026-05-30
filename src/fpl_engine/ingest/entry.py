"""Tracked-team ingestion + transfer detection (plan 9.1).

Pulls an FPL entry's meta, transfer history and current picks through the
shared fetch+snapshot layer, normalises them, and reports transfers newly seen
since the last poll. (Selling prices / bank from the authed /my-team endpoint
are a later addition; public endpoints give purchase costs + team value.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from ..db.engine import get_sessionmaker
from ..db.models import authed_picks, tracked_entries, tracked_picks, tracked_transfers
from ..logging_setup import get_logger
from .fetch import FetchClient

log = get_logger(__name__)


def _ts(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class EntryResult:
    entry_id: int
    name: str
    current_event: int | None
    team_value: int | None
    new_transfers: int
    roster: list[int] = field(default_factory=list)


@dataclass
class MyTeamResult:
    entry_id: int
    authenticated: bool
    needs_reauth: bool = False
    reason: str | None = None
    bank: int | None = None
    team_value: int | None = None
    picks: int = 0


class EntryIngestor:
    PROVIDER = "fpl"

    def __init__(self, fetch: FetchClient, sm: sessionmaker[Session] | None = None):
        self._fetch = fetch
        self._sm = sm or get_sessionmaker()

    def ingest_entry(self, entry_id: int) -> EntryResult:
        meta = self._fetch.get(self.PROVIDER, f"/entry/{entry_id}/").payload
        name = f"{meta.get('player_first_name', '')} {meta.get('player_last_name', '')}".strip()
        current_event = meta.get("current_event")
        team_value = meta.get("last_deadline_value")

        with self._sm() as s:
            stmt = insert(tracked_entries).values(
                entry_id=entry_id, player_name=name, current_event=current_event,
                bank=meta.get("last_deadline_bank"), team_value=team_value,
                total_points=meta.get("summary_overall_points"),
                overall_rank=meta.get("summary_overall_rank"))
            s.execute(stmt.on_conflict_do_update(
                index_elements=["entry_id"],
                set_={c: stmt.excluded[c] for c in
                      ("player_name", "current_event", "bank", "team_value",
                       "total_points", "overall_rank")}))
            s.commit()

        new_transfers = self._ingest_transfers(entry_id)
        roster = self._ingest_picks(entry_id, current_event) if current_event else []

        log.info("entry ingested", extra={"entry_id": entry_id, "player_name": name,
                                          "current_event": current_event,
                                          "new_transfers": new_transfers,
                                          "roster_size": len(roster)})
        return EntryResult(entry_id, name, current_event, team_value, new_transfers, roster)

    def _ingest_transfers(self, entry_id: int) -> int:
        payload = self._fetch.get(self.PROVIDER, f"/entry/{entry_id}/transfers/").payload
        if not isinstance(payload, list):
            return 0
        tt = tracked_transfers.c
        with self._sm() as s:
            existing = {
                (row.transfer_time, row.element_in)
                for row in s.execute(
                    select(tt.transfer_time, tt.element_in).where(tt.entry_id == entry_id)
                ).all()
            }
            new = 0
            rows = []
            for tr in payload:
                t = _ts(tr.get("time"))
                ein = tr.get("element_in")
                if t is None or ein is None:
                    continue
                if (t, ein) not in existing:
                    new += 1
                rows.append({
                    "entry_id": entry_id, "transfer_time": t, "element_in": ein,
                    "event": tr.get("event"), "element_out": tr.get("element_out"),
                    "element_in_cost": tr.get("element_in_cost"),
                    "element_out_cost": tr.get("element_out_cost"),
                })
            if rows:
                stmt = insert(tracked_transfers).values(rows)
                s.execute(stmt.on_conflict_do_nothing(
                    index_elements=["entry_id", "transfer_time", "element_in"]))
                s.commit()
        return new

    def _ingest_picks(self, entry_id: int, event: int) -> list[int]:
        res = self._fetch.get(self.PROVIDER, f"/entry/{entry_id}/event/{event}/picks/")
        if res.status_code != 200:
            return []
        picks = res.payload.get("picks", []) if isinstance(res.payload, dict) else []
        if not picks:
            return []
        rows = [{
            "entry_id": entry_id, "event": event, "element_id": p["element"],
            "slot": p.get("position"), "multiplier": p.get("multiplier"),
            "is_captain": p.get("is_captain"), "is_vice": p.get("is_vice_captain"),
        } for p in picks]
        with self._sm() as s:
            stmt = insert(tracked_picks).values(rows)
            s.execute(stmt.on_conflict_do_nothing(
                index_elements=["entry_id", "event", "element_id", "captured_at"]))
            s.commit()
        return [p["element"] for p in picks]

    def ingest_my_team(self, entry_id: int) -> MyTeamResult:
        """Authed ``/my-team/{id}`` pull: exact selling/purchase prices + bank.

        Requires the operator FPL session cookie (settings, never logged). On a
        missing cookie or an auth rejection (401/403) we DON'T fall over — the
        caller keeps using public data — but we flag ``needs_reauth`` so the
        operator is prompted to refresh the cookie.
        """
        cookie = get_settings().fpl_session_cookie
        if cookie is None:
            log.warning("my-team skipped: no session cookie", extra={"entry_id": entry_id})
            return MyTeamResult(entry_id, authenticated=False, needs_reauth=True,
                                reason="no_cookie")

        res = self._fetch.get(self.PROVIDER, f"/my-team/{entry_id}/",
                              extra_headers={"Cookie": cookie.get_secret_value()})
        if res.status_code in (401, 403):
            log.warning("my-team auth failed; re-auth needed",
                        extra={"entry_id": entry_id, "status": res.status_code})
            return MyTeamResult(entry_id, authenticated=False, needs_reauth=True,
                                reason="auth_failed")
        if res.status_code != 200 or not isinstance(res.payload, dict):
            return MyTeamResult(entry_id, authenticated=False,
                                reason=f"status_{res.status_code}")

        payload = res.payload
        transfers = payload.get("transfers") or {}
        bank = transfers.get("bank")
        value = transfers.get("value")
        picks = payload.get("picks") or []
        rows = [{
            "entry_id": entry_id, "element_id": p["element"],
            "selling_price": p.get("selling_price"),
            "purchase_price": p.get("purchase_price"),
            "multiplier": p.get("multiplier"),
            "is_captain": p.get("is_captain"), "is_vice": p.get("is_vice_captain"),
        } for p in picks if p.get("element") is not None]

        with self._sm() as s:
            if rows:
                s.execute(insert(authed_picks).values(rows).on_conflict_do_nothing(
                    index_elements=["entry_id", "element_id", "captured_at"]))
            # Authed bank/value are live + exact -> override the public snapshot.
            if bank is not None or value is not None:
                stmt = insert(tracked_entries).values(
                    entry_id=entry_id, bank=bank, team_value=value)
                s.execute(stmt.on_conflict_do_update(
                    index_elements=["entry_id"],
                    set_={"bank": stmt.excluded.bank, "team_value": stmt.excluded.team_value}))
            s.commit()
        log.info("my-team ingested", extra={"entry_id": entry_id, "picks": len(rows),
                                            "bank": bank})
        return MyTeamResult(entry_id, authenticated=True, bank=bank,
                            team_value=value, picks=len(rows))

    def _authed_purchase(self, s: Session, entry_id: int) -> dict[int, int]:
        """Latest-snapshot {element_id: purchase_price} from authed picks."""
        ap = authed_picks.c
        latest = s.execute(
            select(ap.captured_at).where(ap.entry_id == entry_id)
            .order_by(ap.captured_at.desc()).limit(1)
        ).scalar_one_or_none()
        if latest is None:
            return {}
        rows = s.execute(
            select(ap.element_id, ap.purchase_price).where(
                ap.entry_id == entry_id, ap.captured_at == latest,
                ap.purchase_price.isnot(None))
        ).all()
        return {r.element_id: int(r.purchase_price) for r in rows}

    def latest_roster(self, entry_id: int) -> list[int]:
        tp = tracked_picks.c
        with self._sm() as s:
            event = s.execute(
                select(tp.event).where(tp.entry_id == entry_id)
                .order_by(tp.event.desc()).limit(1)
            ).scalar_one_or_none()
            if event is None:
                return []
            captured = s.execute(
                select(tp.captured_at).where(tp.entry_id == entry_id, tp.event == event)
                .order_by(tp.captured_at.desc()).limit(1)
            ).scalar_one()
            rows = s.execute(
                select(tp.element_id).where(
                    tp.entry_id == entry_id, tp.event == event, tp.captured_at == captured)
            ).all()
        return [r[0] for r in rows]

    def resolve_budget(self, entry_id: int) -> tuple[int | None, dict[int, int]]:
        """Return ``(bank, purchase_by_element)`` for the value-aware planner.

        Prefers **authed** data when present: exact per-player purchase prices
        from ``/my-team`` (every owned player, including the initial squad).
        Otherwise falls back to public transfer history — the most-recent
        ``element_in_cost`` per currently-held player; players never transferred
        in won't appear, so the planner assumes no value gain on those.
        """
        te = tracked_entries.c
        tt = tracked_transfers.c
        with self._sm() as s:
            bank = s.execute(
                select(te.bank).where(te.entry_id == entry_id)
            ).scalar_one_or_none()
            authed = self._authed_purchase(s, entry_id)
            if authed:
                return (int(bank) if bank is not None else None), authed
            rows = s.execute(
                select(tt.element_in, tt.transfer_time, tt.element_in_cost)
                .where(tt.entry_id == entry_id, tt.element_in_cost.isnot(None))
                .order_by(tt.transfer_time.asc())
            ).all()
        # Last in-cost per element wins (overwrites earlier buys of the same id).
        purchase = {r.element_in: int(r.element_in_cost) for r in rows}
        # Keep only currently-held players so a re-bought transferred-out player
        # doesn't pollute the dict for someone we don't actually own.
        held = set(self.latest_roster(entry_id))
        purchase = {pid: c for pid, c in purchase.items() if pid in held}
        return (int(bank) if bank is not None else None), purchase
