"""Strictly-causal walk-forward training panel (plan 3.1).

One row per (player, season, GW) prediction point. Features are built only from
the player's matches *strictly before* that GW's deadline (the appearance
sequence spans all prior seasons, so long windows work); targets are realised
points over the horizon at/after the deadline ({next1, next6, rest-of-season}).

``hist_last_kickoff`` and ``tgt_first_kickoff`` are persisted so a leakage audit
can assert ``hist_last_kickoff < deadline <= tgt_first_kickoff`` for every row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import player_advanced_match_stats, player_match_stats, targets, training_rows
from ..logging_setup import get_logger
from .windows import EWMA_LOOKBACK, per90, window_features

log = get_logger(__name__)

FEATURE_VERSION = "p1.1"
_FAR_PAST = datetime(1900, 1, 1, tzinfo=timezone.utc)

# Advanced per-match metrics merged from player_advanced_match_stats (Understat
# xG family + FBref creation/progression). Ragged history (NULL before each
# source's span) is handled by the windowing's null-filter -> no dilution.
ADVANCED_METRICS = (
    "npxg", "xg_chain", "xg_buildup", "key_passes", "shots",   # understat
    "sca", "gca", "prog_passes", "prog_carries",               # fbref
)

# Metrics windowed over the appearance sequence (Phase-1, stats-only sources).
WINDOW_METRICS = (
    "minutes", "starts", "played", "total_points", "goals_scored", "assists",
    "clean_sheets", "goals_conceded", "saves", "bonus", "bps",
    "influence", "creativity", "threat", "ict_index",
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "expected_goals_conceded",
    "tackles", "clearances_blocks_interceptions", "recoveries", "defensive_contribution",
) + ADVANCED_METRICS
# (metric, per-90 feature name) computed over the last 38 appearances.
PER90_METRICS = (
    ("goals_scored", "goals90"), ("assists", "assists90"),
    ("expected_goals", "xg90"), ("expected_assists", "xa90"),
    ("expected_goal_involvements", "xgi90"),
    ("npxg", "npxg90"), ("key_passes", "key_passes90"),
    ("sca", "sca90"), ("gca", "gca90"),
)


@dataclass
class PanelBuildResult:
    season: str
    rows: int


@dataclass
class _SeasonGw:
    pts: int = 0
    pts_norm: float = 0.0
    minutes: int = 0
    min_kickoff: datetime | None = None


def _num(v) -> float:
    return float(v) if v is not None else 0.0


class PanelBuilder:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def build(
        self,
        seasons: Iterable[str] | None = None,
        *,
        min_history: int = 1,
    ) -> list[PanelBuildResult]:
        want = set(seasons) if seasons is not None else None
        by_player = self._load()
        counts: dict[str, int] = {}
        batch: list[dict] = []

        with self._sm() as s:
            for player_key, matches in by_player.items():
                matches.sort(key=self._sort_key)
                season_idx = self._season_index(matches)
                groups = self._ordered_groups(matches)

                recent: list[dict] = []           # last EWMA_LOOKBACK match dicts
                career_sum: dict[str, float] = {m: 0.0 for m in WINDOW_METRICS}
                career_n: dict[str, int] = {m: 0 for m in WINDOW_METRICS}
                hist_n = 0
                hist_last_kickoff: datetime | None = None

                for (season, gw), group in groups:
                    if hist_n >= min_history and (want is None or season in want):
                        row = self._make_row(
                            player_key, season, gw, season_idx, recent,
                            career_sum, career_n, hist_n, hist_last_kickoff, group[0],
                        )
                        batch.append(row)
                        counts[season] = counts.get(season, 0) + 1

                    # advance history with this GW's matches (now "in the past")
                    for m in group:
                        self._absorb(m, recent, career_sum, career_n)
                        hist_n += 1
                        kt = m["kickoff_time"]
                        if kt and (hist_last_kickoff is None or kt > hist_last_kickoff):
                            hist_last_kickoff = kt

            self._flush(s, batch)
            s.commit()

        results = [PanelBuildResult(season, n) for season, n in sorted(counts.items())]
        for r in results:
            log.info("training_rows built", extra={"season": r.season, "rows": r.rows})
        return results

    # -- data loading --
    def _load(self) -> dict[int, list[dict]]:
        t, p = targets.c, player_match_stats.c
        stmt = (
            select(
                t.season, t.player_key, t.gw, t.element_id, t.element_type,
                t.actual_points, t.normalised_points,
                p.fixture_id, p.kickoff_time, p.minutes, p.goals_scored, p.assists,
                p.clean_sheets, p.goals_conceded, p.saves, p.bonus, p.bps,
                p.influence, p.creativity, p.threat, p.ict_index,
                p.expected_goals, p.expected_assists, p.expected_goal_involvements,
                p.expected_goals_conceded, p.tackles,
                p.clearances_blocks_interceptions, p.recoveries, p.defensive_contribution,
            )
            .select_from(targets.join(
                player_match_stats,
                (t.season == p.season) & (t.element_id == p.element_id)
                & (t.fixture_id == p.fixture_id),
            ))
            .where(t.player_key.isnot(None))
        )
        by_player: dict[int, list[dict]] = {}
        with self._sm() as s:
            for r in s.execute(stmt).mappings():
                d = dict(r)
                # A match with no kickoff cannot be causally ordered; excluding
                # it keeps the appearance sequence (and the leakage guarantee)
                # well-defined. None exist today; this is a guard for new feeds.
                if d["kickoff_time"] is None:
                    continue
                mins = d["minutes"] or 0
                d["starts"] = 1 if mins >= 60 else 0
                d["played"] = 1 if mins > 0 else 0
                d["total_points"] = d["actual_points"]  # window metric alias
                by_player.setdefault(d["player_key"], []).append(d)

        self._merge_advanced(by_player)
        return by_player

    def _merge_advanced(self, by_player: dict[int, list[dict]]) -> None:
        """Attach advanced metrics to each match dict by (season, player_key,
        fixture_id), coalescing the Understat + FBref source rows."""
        a = player_advanced_match_stats.c
        merged: dict[tuple, dict[str, float]] = {}
        with self._sm() as s:
            rows = s.execute(
                select(a.season, a.player_key, a.fixture_id, a.npxg, a.xg_chain,
                       a.xg_buildup, a.key_passes, a.shots, a.sca, a.gca,
                       a.prog_passes, a.prog_carries)
                .where(a.player_key.isnot(None), a.fixture_id.isnot(None))
            ).mappings().all()
        for r in rows:
            key = (r["season"], r["player_key"], r["fixture_id"])
            bucket = merged.setdefault(key, {})
            for m in ADVANCED_METRICS:
                # First non-null across sources wins (sources own disjoint cols).
                if bucket.get(m) is None and r[m] is not None:
                    bucket[m] = float(r[m])

        for matches in by_player.values():
            for d in matches:
                adv = merged.get((d["season"], d["player_key"], d["fixture_id"]), {})
                for m in ADVANCED_METRICS:
                    d[m] = adv.get(m)

    @staticmethod
    def _sort_key(m: dict):
        return (m["kickoff_time"] or _FAR_PAST, m["season"], m["gw"], m["fixture_id"])

    def _season_index(self, matches: list[dict]) -> dict[str, dict[int, _SeasonGw]]:
        idx: dict[str, dict[int, _SeasonGw]] = {}
        for m in matches:
            sg = idx.setdefault(m["season"], {}).setdefault(m["gw"], _SeasonGw())
            sg.pts += m["actual_points"] or 0
            sg.pts_norm += _num(m["normalised_points"])
            sg.minutes += m["minutes"] or 0
            kt = m["kickoff_time"]
            if kt and (sg.min_kickoff is None or kt < sg.min_kickoff):
                sg.min_kickoff = kt
        return idx

    @staticmethod
    def _ordered_groups(matches: list[dict]) -> list[tuple[tuple[str, int], list[dict]]]:
        groups: dict[tuple[str, int], list[dict]] = {}
        order: list[tuple[str, int]] = []
        for m in matches:
            key = (m["season"], m["gw"])
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(m)
        return [(k, groups[k]) for k in order]

    @staticmethod
    def _absorb(m: dict, recent: list[dict], career_sum, career_n) -> None:
        recent.append(m)
        if len(recent) > EWMA_LOOKBACK:
            del recent[0]
        for metric in WINDOW_METRICS:
            v = m.get(metric)
            if v is not None:
                career_sum[metric] += float(v)
                career_n[metric] += 1

    # -- feature + target assembly for one prediction point --
    def _make_row(self, player_key, season, gw, season_idx, recent,
                  career_sum, career_n, hist_n, hist_last_kickoff, sample) -> dict:
        feats: dict[str, float | None] = {}
        for metric in WINDOW_METRICS:
            # cast at the DB boundary: Numeric columns arrive as Decimal
            values = [float(r[metric]) for r in recent if r.get(metric) is not None]
            wf = window_features(values, career_sum=career_sum[metric],
                                 career_n=career_n[metric])
            for k, v in wf.items():
                # Keep levels/EWMA/career-mean/momentum; drop raw sums (size).
                if k.startswith("sum_") or k == "career_sum":
                    continue
                feats[f"{metric}__{k}"] = v

        last38 = recent[-38:]
        for metric, name in PER90_METRICS:
            # Align numerator and denominator: only count minutes from matches
            # where the metric is observed (a ragged metric like xG is NULL
            # before 2022/23, so those minutes must not dilute the per-90).
            present = [r for r in last38 if r.get(metric) is not None]
            msum = float(sum(r[metric] for r in present))
            minsum = float(sum((r["minutes"] or 0) for r in present))
            feats[name] = per90(msum, minsum)

        sgw = season_idx[season]
        n1 = sgw[gw]
        next6 = [sgw[g] for g in range(gw, gw + 6) if g in sgw]
        ros = [sgw[g] for g in sgw if g >= gw]
        deadline = n1.min_kickoff

        return {
            "season": season, "player_key": player_key, "gw": gw,
            "element_id": sample["element_id"], "element_type": sample["element_type"],
            "deadline": deadline, "hist_n": hist_n,
            "hist_last_kickoff": hist_last_kickoff, "tgt_first_kickoff": deadline,
            "tgt_pts_next1": n1.pts,
            "tgt_pts_next6": sum(x.pts for x in next6),
            "tgt_pts_ros": sum(x.pts for x in ros),
            "tgt_pts_norm_next1": round(n1.pts_norm, 2),
            "tgt_pts_norm_next6": round(sum(x.pts_norm for x in next6), 2),
            "tgt_pts_norm_ros": round(sum(x.pts_norm for x in ros), 2),
            "tgt_minutes_next1": n1.minutes,
            "n_gw_next6": len(next6), "n_gw_ros": len(ros),
            "features": feats, "feature_version": FEATURE_VERSION,
        }

    def _flush(self, s: Session, batch: list[dict]) -> None:
        for i in range(0, len(batch), 500):
            chunk = batch[i:i + 500]
            if not chunk:
                continue
            stmt = insert(training_rows).values(chunk)
            update = {c: stmt.excluded[c] for c in chunk[0]
                      if c not in ("season", "player_key", "gw")}
            s.execute(stmt.on_conflict_do_update(
                index_elements=["season", "player_key", "gw"], set_=update))

    def leakage_audit(self, season: str | None = None) -> dict:
        """Assert no row uses data at/after its deadline.

        Returns counts of violations: history reaching the deadline, or the
        target window starting before it.
        """
        tr = training_rows.c
        with self._sm() as s:
            base = select(tr.season).where(tr.hist_n > 0)
            if season:
                base = base.where(tr.season == season)
            total = len(s.execute(base).all())
            hist_violations = len(s.execute(
                base.where(tr.hist_last_kickoff >= tr.deadline)).all())
            tgt_violations = len(s.execute(
                base.where(tr.tgt_first_kickoff < tr.deadline)).all())
        return {
            "season": season or "all", "rows_audited": total,
            "history_after_deadline": hist_violations,
            "target_before_deadline": tgt_violations,
            "ok": hist_violations == 0 and tgt_violations == 0,
        }

    def independent_leakage_audit(self, season: str | None = None) -> dict:
        """Re-derive the causal cutoff from player_match_stats, independent of
        the builder's stored bookkeeping.

        For every training row, recompute from the raw match table the number
        and latest kickoff of the player's matches strictly before the deadline,
        and require them to equal the stored ``hist_n`` / ``hist_last_kickoff``.
        A divergence would reveal a leak the by-construction audit cannot.
        """
        from bisect import bisect_left

        by_player = self._load()
        kickoffs: dict[int, list[datetime]] = {
            pk: sorted(m["kickoff_time"] for m in matches)
            for pk, matches in by_player.items()
        }

        tr = training_rows.c
        stmt = select(tr.season, tr.player_key, tr.gw, tr.deadline,
                      tr.hist_last_kickoff, tr.hist_n)
        if season:
            stmt = stmt.where(tr.season == season)

        checked = mismatches = 0
        with self._sm() as s:
            rows = s.execute(stmt).all()
        for r in rows:
            checked += 1
            seq = kickoffs.get(r.player_key, [])
            cut = bisect_left(seq, r.deadline)  # count of kickoffs strictly < deadline
            exp_n = cut
            exp_last = seq[cut - 1] if cut > 0 else None
            if exp_n != r.hist_n or exp_last != r.hist_last_kickoff:
                mismatches += 1
        return {
            "season": season or "all", "rows_checked": checked,
            "mismatches": mismatches, "ok": mismatches == 0,
        }
