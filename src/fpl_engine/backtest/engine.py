"""Predictor-driven, strictly-causal strategy backtester (plan 10.1).

Replays a season GW-by-GW. The expected-points signal for each player at GW *g*
comes from a pluggable :class:`Predictor` applied to that player's
``training_rows`` features — which the Phase-3 audit proved are built only from
matches *before* g. The chosen XI/captain/transfers are then scored on g's
*actual* points. Free-transfer accrual and −4 hits are tracked as in live play.

Because every candidate signal (last-GW, form, PPG, the frozen model, …) reads
the same causal panel, ``compare`` ranks them head-to-head on realised points —
answering "which approach best predicts points?" without look-ahead.

Prices use each GW's actual ``value``; team comes from ``normalised.players``.
No auto-subs (XI-only), which understates every strategy equally.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import (
    backtest_runs,
    players,
    player_match_stats,
    team_match_stats,
    training_rows,
)
from ..logging_setup import get_logger
from ..model.predictors import Predictor, default_predictors
from ..optimise.squad import BUDGET, Candidate, SquadOptimizer, selling_price
from ..optimise.transfer import MAX_FT, PlayerH
from ..optimise.value_step import GwPlayer, value_aware_gw

log = get_logger(__name__)

# Top-N candidates PER POSITION. Per-position (not a global top-N) so a
# position-skewed signal (e.g. xGI/ICT, which score GKs/defenders ~0) still
# yields a pool that can field a legal 2/5/5/3 squad under max-3-per-club.
PER_POS_POOL = {1: 6, 2: 25, 3: 25, 4: 15}

GK, DEF, MID, FWD = 1, 2, 3, 4
_POS_MAX = {GK: 1, DEF: 5, MID: 5, FWD: 3}   # XI position ceilings (valid formation)


def realise_gw(xi: list[int], squad: set[int], captain: int,
               actual: dict[int, int], pos: dict[int, int], xp: dict[int, float],
               *, cap_mult: int = 2, bench_boost: bool = False) -> tuple[int, int, int | None]:
    """Realised GW points with autosubs, vice-captain and optional bench boost.

    ``actual[id]==0`` means "did not play" (any appearance scores >=1), so a
    blanking starter is replaced by the highest-xP bench player who played while
    keeping a valid position split (GK only subs GK; <=1 GK / <=5 DEF / <=5 MID
    / <=3 FWD). The vice-captain (highest-xP non-captain starter) inherits the
    armband if the captain blanks. Bench boost scores all 15. Returns
    (points, n_autosubs, effective_captain).
    """
    from collections import Counter
    starters = list(xi)
    xi_set = set(xi)
    bench = [e for e in squad if e not in xi_set]

    if bench_boost:
        scoring = list(squad)
        n_subs = 0
    else:
        scoring = [e for e in starters if actual.get(e, 0) > 0]
        subs = sorted((b for b in bench if actual.get(b, 0) > 0),
                      key=lambda b: xp.get(b, 0.0), reverse=True)
        n_subs = 0
        for b in subs:
            if len(scoring) >= 11:
                break
            c = Counter(pos.get(i) for i in scoring)
            c[pos.get(b)] += 1
            if all(c.get(p, 0) <= cap for p, cap in _POS_MAX.items()):
                scoring.append(b)
                n_subs += 1

    base = sum(actual.get(e, 0) for e in scoring)
    vice = max((e for e in starters if e != captain),
               key=lambda e: xp.get(e, 0.0), default=None)
    if actual.get(captain, 0) > 0:
        eff_cap = captain
    elif vice is not None and actual.get(vice, 0) > 0:
        eff_cap = vice
    else:
        eff_cap = None
    bonus = (cap_mult - 1) * actual.get(eff_cap, 0) if eff_cap is not None else 0
    return base + bonus, n_subs, eff_cap


@dataclass
class _Frame:
    pos: int
    price: int
    team: int
    actual: int
    features: dict
    fixtures: int = 1       # >1 in a double gameweek (player plays twice)
    opponent: int | None = None


@dataclass
class BacktestResult:
    season: str
    strategy: str
    start_gw: int
    end_gw: int
    total_points: int
    total_hits: int
    net_points: int
    per_gw: list[dict] = field(default_factory=list)
    # Chip bonuses (xP-timed): Triple Captain + Bench Boost, and net incl. chips.
    chip_bonus: int = 0
    net_with_chips: int = 0
    chips: dict = field(default_factory=dict)


class Backtester:
    def __init__(self, sm: sessionmaker[Session] | None = None, model_version: str = "v1",
                 ft_value: float = 0.0, free_hit: bool = False):
        self._sm = sm or get_sessionmaker()
        self.model_version = model_version
        # Opportunity cost of using a free transfer (transfer-planning discipline):
        # a per-GW transfer is only made when its xP gain exceeds ft_value.
        self.ft_value = ft_value
        # Free Hit chip: when enabled, measure (per GW) the gain from fielding a
        # fully-optimal one-week squad vs the current squad, and add the best one.
        self.free_hit = free_hit

    # -- causal panel + actuals --
    def _frames(self, season: str, gws: list[int]) -> dict[int, dict[int, _Frame]]:
        tr, m, pl = training_rows.c, player_match_stats.c, players.c
        with self._sm() as s:
            rows = s.execute(
                select(tr.gw, tr.element_id, tr.element_type, tr.features,
                       m.value, m.total_points, pl.team_id, m.opponent_team_id)
                .select_from(
                    training_rows
                    .join(player_match_stats,
                          (m.season == tr.season) & (m.element_id == tr.element_id)
                          & (m.gw == tr.gw))
                    .join(players, pl.id == tr.element_id))
                .where(tr.season == season, tr.gw.in_(gws),
                       m.value.isnot(None), pl.team_id.isnot(None))
            ).all()
        frames: dict[int, dict[int, _Frame]] = defaultdict(dict)
        for r in rows:
            f = frames[r.gw].get(r.element_id)
            if f is None:
                frames[r.gw][r.element_id] = _Frame(
                    pos=r.element_type, price=int(r.value), team=r.team_id,
                    actual=int(r.total_points or 0), features=dict(r.features or {}),
                    opponent=r.opponent_team_id)
            else:  # double gameweek: sum the actual points + count the fixture
                f.actual += int(r.total_points or 0)
                f.fixtures += 1
        self._inject_opponent_strength(season, frames)
        return frames

    def _opponent_factors(self, season: str) -> dict[tuple[int, int], tuple[float, float]]:
        """(gw, team) -> (attack_factor, defence_leak_factor), each a team's
        STRICTLY-PRIOR mean goals-for / goals-against relative to the league
        average, shrunk toward 1.0 early in the season. Causal (only past GWs)."""
        tms = team_match_stats.c
        with self._sm() as s:
            rows = s.execute(
                select(tms.gw, tms.team_id, tms.goals_for, tms.goals_against)
                .where(tms.season == season,
                       tms.goals_for.isnot(None), tms.goals_against.isnot(None))
                .order_by(tms.gw)
            ).all()
        if not rows:
            return {}
        league_avg = sum(r.goals_for for r in rows) / len(rows)
        if league_avg <= 0:
            return {}
        by_team: dict[int, list] = defaultdict(list)
        for r in rows:
            by_team[r.team_id].append(r)
        k = 4.0   # shrinkage strength toward the league average
        out: dict[tuple[int, int], tuple[float, float]] = {}
        for team, recs in by_team.items():
            gf = ga = 0.0
            n = 0
            for r in recs:
                att = (gf + k * league_avg) / (n + k) / league_avg
                deff = (ga + k * league_avg) / (n + k) / league_avg
                out[(r.gw, team)] = (att, deff)
                gf += r.goals_for
                ga += r.goals_against
                n += 1
        return out

    def _inject_opponent_strength(self, season: str, frames: dict) -> None:
        """Attach the opponent's attack/defence factors to each player's features
        so the (opponent-aware) component model can scale its rates."""
        factors = self._opponent_factors(season)
        if not factors:
            return
        for gw, fr in frames.items():
            for f in fr.values():
                if f.opponent is None:
                    continue
                att, deff = factors.get((gw, f.opponent), (1.0, 1.0))
                # opponent's defensive leak boosts our attack; their attack
                # strength threatens our clean sheet.
                f.features["opp_def"] = round(deff, 4)
                f.features["opp_att"] = round(att, 4)

    def _pool(self, frame, squad, carry, predictor: Predictor):
        # cohort scoring so ensembles can normalise across the GW's players
        scored = predictor.score_frame([(eid, f.features, f.pos)
                                        for eid, f in frame.items()])
        # DGW-aware xP: a player with two fixtures this GW expects ~twice the
        # single-match signal. Fixtures are known in advance, so scaling the
        # causal signal by the fixture count makes the optimiser/captaincy/chips
        # value double-gameweek players correctly (and ignore blank-GW ones).
        dgw = {eid: scored[eid] * frame[eid].fixtures for eid in frame}
        # keep the top-N per position (+ current squad) so the pool can always
        # form a legal squad even when the signal is position-skewed.
        by_pos: dict[int, list[int]] = defaultdict(list)
        for eid, f in frame.items():
            by_pos[f.pos].append(eid)
        keep = set(squad)
        for pos, eids in by_pos.items():
            eids.sort(key=lambda e: dgw[e], reverse=True)
            keep |= set(eids[:PER_POS_POOL.get(pos, 20)])
        # a blanking held player should rank below every player who features this
        # GW, on the SAME scale as the (DGW-scaled) signal.
        floor = (min(dgw.values()) - 1.0) if dgw else 0.0
        pool: list[PlayerH] = []
        actual: dict[int, int] = {}
        for eid in keep:
            if eid in frame:
                f = frame[eid]
                pos, price, team, act, xp = f.pos, f.price, f.team, f.actual, dgw[eid]
            elif eid in carry:  # held player blank this GW
                pos, price, team = carry[eid]
                act, xp = 0, floor
            else:
                continue
            pool.append(PlayerH(eid, pos, price, team, [xp], name=str(eid)))
            actual[eid] = act
        return pool, actual

    def run(self, season: str, gws: list[int], predictor: Predictor,
            policy: str = "active") -> BacktestResult:
        gws = sorted(gws)
        frames = self._frames(season, gws)
        # Online predictors (e.g. Hedge) carry adaptive state; reset it so this
        # run starts from the leakage-free prior, never a prior run's state.
        if hasattr(predictor, "reset"):
            predictor.reset()

        squad: set[int] | None = None
        purchase: dict[int, int] = {}   # eid -> price paid (tenths)
        bank = 0                        # leftover cash (tenths)
        ft = 1
        gross = hits = 0
        carry: dict[int, tuple[int, int, int]] = {}
        per_gw: list[dict] = []

        def skip(gw: int, reason: str) -> None:  # keep GW sets identical across predictors
            per_gw.append({"gw": gw, "points": 0, "hit": 0, "transfers": 0,
                           "captain": None, "skipped": reason})

        for gw in gws:
            frame = frames.get(gw)
            if not frame:
                skip(gw, "no_data")
                continue
            for eid, f in frame.items():
                carry[eid] = (f.pos, f.price, f.team)

            pool, actual = self._pool(frame, squad or set(), carry, predictor)
            if not pool:
                skip(gw, "empty_pool")
                continue
            pos_by = {p.id: p.position for p in pool}
            xp_by = {p.id: p.xp[0] for p in pool}

            if squad is None:  # build the initial squad within the £100.0m cap
                cands = [Candidate(p.id, p.position, p.price, p.team_id, p.xp[0])
                         for p in pool]
                sol = SquadOptimizer(budget=BUDGET).solve(cands)
                if not sol.feasible:
                    log.warning("backtest squad infeasible", extra={"gw": gw})
                    skip(gw, "init_infeasible")
                    continue
                squad = {p.id for p in sol.picks}
                purchase = {p.id: p.price for p in sol.picks}
                bank = BUDGET - sum(purchase.values())
                xi = [p.id for p in sol.picks if p.is_start]
                captain = next(p.id for p in sol.picks if p.is_captain)
                hit, n_in = 0, 0
            else:
                # transact under the REAL evolving budget (bank + sell values),
                # using this GW's actual prices.
                gplayers = [GwPlayer(p.id, p.position, p.price, p.team_id, p.xp[0], p.p_play)
                            for p in pool]
                step = value_aware_gw(squad, purchase, bank, gplayers, ft=ft,
                                      ft_value=self.ft_value, lock=(policy == "hold"))
                if not step.feasible:
                    skip(gw, "plan_infeasible")
                    continue
                xi, captain, hit = step.xi, step.captain, step.hit
                n_in = len(step.transfers_in)
                squad, purchase, bank = set(step.squad), step.purchase, step.bank

            gw_pts, n_subs, eff_cap = realise_gw(xi, squad, captain, actual, pos_by, xp_by)
            # Chip uplifts (measured each GW; the best GW is chosen post-hoc by
            # the xP timing signal, i.e. good-but-causal chip usage, not hindsight
            # on realised points). TC = +1x the armband player; BB = all 15 score.
            tc_uplift = actual.get(eff_cap, 0)
            cap_xp = xp_by.get(captain, 0.0)
            bb_pts, _, _ = realise_gw(xi, squad, captain, actual, pos_by, xp_by,
                                      bench_boost=True)
            bb_uplift = bb_pts - gw_pts
            bench_xp = sum(xp_by.get(e, 0.0) for e in squad if e not in set(xi))
            ft = min(MAX_FT, ft - min(n_in, ft) + 1)
            gross += gw_pts
            hits += hit
            sv = sum(selling_price(purchase[e], carry[e][1]) for e in squad if e in purchase)
            row = {"gw": gw, "points": gw_pts, "hit": hit, "transfers": n_in,
                   "captain": eff_cap, "autosubs": n_subs,
                   "squad_value": sv + bank, "bank": bank,
                   "cap_xp": round(cap_xp, 3), "tc_uplift": tc_uplift,
                   "bench_xp": round(bench_xp, 3), "bb_uplift": bb_uplift}
            if self.free_hit:
                # one-week fully-optimal squad within the real team value (free).
                fh = self._free_hit_value(pool, actual, pos_by, xp_by,
                                          team_value=sv + bank,
                                          current_xp=sum(xp_by.get(e, 0.0) for e in xi)
                                          + xp_by.get(captain, 0.0),
                                          current_pts=gw_pts)
                row["fh_uplift"], row["fh_xp_gap"] = fh
            per_gw.append(row)

            # Online weight update from THIS GW's realised points — called after
            # scoring/selection, so it only informs FUTURE GWs (causal, no leak).
            if hasattr(predictor, "observe"):
                predictor.observe([(eid, fr.features, fr.pos) for eid, fr in frame.items()],
                                  {eid: fr.actual for eid, fr in frame.items()})

        strategy = predictor.name if policy == "active" else f"hold:{predictor.name}"
        chip_bonus, chips = self._chip_bonuses(per_gw)
        result = BacktestResult(
            season=season, strategy=strategy, start_gw=gws[0], end_gw=gws[-1],
            total_points=gross, total_hits=hits, net_points=gross - hits, per_gw=per_gw,
            chip_bonus=chip_bonus, net_with_chips=gross - hits + chip_bonus, chips=chips)
        self._store(result)
        log.info("backtest done", extra={"season": season, "strategy": strategy,
                                         "net_points": result.net_points, "hits": hits})
        return result

    def _free_hit_value(self, pool, actual, pos_by, xp_by, *, team_value,
                        current_xp, current_pts) -> tuple[int, float]:
        """(realised uplift, xP gap) of a one-week fully-optimal squad vs the
        current one, within the real team value. The xP gap is the causal timing
        signal; the realised uplift is what Free Hit would actually add."""
        cands = [Candidate(p.id, p.position, p.price, p.team_id, p.xp[0]) for p in pool]
        sol = SquadOptimizer(budget=int(team_value)).solve(cands)
        if not sol.feasible:
            return 0, 0.0
        fh_squad = {p.id for p in sol.picks}
        fh_xi = [p.id for p in sol.picks if p.is_start]
        fh_cap = next((p.id for p in sol.picks if p.is_captain), None)
        fh_pts, _, _ = realise_gw(fh_xi, fh_squad, fh_cap, actual, pos_by, xp_by)
        return max(0, fh_pts - current_pts), round(sol.xi_xp - current_xp, 3)

    @staticmethod
    def _chip_bonuses(per_gw: list[dict]) -> tuple[int, dict]:
        """Triple Captain + Bench Boost + Free Hit, each played at the GW its xP
        timing signal is highest (good-but-causal usage). One of each per season."""
        played = [g for g in per_gw if "skipped" not in g]
        if not played:
            return 0, {}
        tc = max(played, key=lambda g: g.get("cap_xp", 0.0))
        bb = max(played, key=lambda g: g.get("bench_xp", 0.0))
        tc_pts, bb_pts = int(tc.get("tc_uplift", 0)), int(bb.get("bb_uplift", 0))
        chips = {"triple_captain": {"gw": tc["gw"], "uplift": tc_pts},
                 "bench_boost": {"gw": bb["gw"], "uplift": bb_pts}}
        total = tc_pts + bb_pts
        # Free Hit (only when measured): best GW by the fresh-vs-current xP gap.
        fh_gws = [g for g in played if "fh_xp_gap" in g]
        if fh_gws:
            fh = max(fh_gws, key=lambda g: g.get("fh_xp_gap", 0.0))
            fh_pts = int(fh.get("fh_uplift", 0))
            chips["free_hit"] = {"gw": fh["gw"], "uplift": fh_pts}
            total += fh_pts
        return total, chips

    def compare(self, season: str, gws: list[int],
                predictors: dict[str, Predictor] | None = None) -> dict[str, BacktestResult]:
        predictors = predictors or default_predictors()
        results = {name: self.run(season, gws, pred, "active")
                   for name, pred in predictors.items()}
        base = predictors.get("ppg_career") or next(iter(predictors.values()))
        results["hold"] = self.run(season, gws, base, "hold")
        return results

    def _store(self, r: BacktestResult) -> None:
        with self._sm() as s:
            s.execute(insert(backtest_runs).values(
                model_version=self.model_version, season=r.season, strategy=r.strategy,
                start_gw=r.start_gw, end_gw=r.end_gw, total_points=r.total_points,
                total_hits=r.total_hits, net_points=r.net_points, per_gw=r.per_gw))
            s.commit()
