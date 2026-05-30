# FPL Intelligence Engine — Master Multi-Phase Implementation Plan (v2)

*Single source of truth. Supersedes FPL_MASTER_PLAN.md (v1), FPL_MODULE_DECISIONS_AND_BUILD.md, FPL_OPEN_ITEMS_RESOLVED.md, and FPL_FREE_ODDS_APIS.md — all folded in. All decisions locked; no open decisions outstanding.*

---

## How to read this

- **Part A** — system overview, architecture, conventions.
- **Part B** — datapoint catalogs & rules (datapoints at all levels): sources, FPL endpoints, every field, the free odds-API layer, the 2025/26 ruleset, the window bank, target conversion, per-position feature families.
- **Part C** — model & optimiser specs.
- **Part D** — phased build: 11 phases, ~32 dependency-ordered, self-contained stages (Depends · Instructions · Datapoints · Output · Done).
- **Part E** — data model, glossary, locked decisions, standing risks.

**Locked decisions (carried throughout):** free-stack data only; **Betfair Exchange (Delayed App Key)** as primary odds source, supplemented by free-tier odds APIs (SharpAPI/SGO/OddsPapi/odds-api.io/API-Football); optimiser horizon **5–8 GW, default 6**; notifications via **Pushover + email**; store the operator's **FPL session cookie** for `/my-team`.

---
---

# PART A — System overview

## A.1 What it does

A self-hosted service that (1) **ingests** every obtainable datapoint on PL teams, players, coaches, fixtures, FPL game-state, **sharp betting odds**, and the **squads of elite FPL managers**; (2) **learns**, from history, which stats over which lookback windows predict future output, per position; (3) **predicts** each player's expected FPL points (xP) component-by-component; (4) **optimises** a 15-man squad and a multi-gameweek transfer/captain/chip plan under the full ruleset; (5) **tracks** a given FPL entry, detects its transfers, and **pushes** transfer/captain recommendations; (6) **runs continuously**, re-scoring as prices, lineups, odds and news change.

## A.2 Architecture

```
 Scheduler / Orchestrator ──dispatches──┐  (cron-like + event triggers; per-provider budget tracking)
                                        ▼
  ┌──────── INGESTORS (shared rate-limited fetch layer) ─────────────────────┐
  │ FPL · Advanced stats · Multi-source ODDS · Elite-manager · Lineups/news    │
  └───────────────────────────┬───────────────────────────────────────────────┘
                              ▼
        Postgres (+ TimescaleDB):  RAW → NORMALISED → FEATURE  (3 layers, never overwrite history)
                              ▼
        Feature builder (windowing, per-90, splits)  +  Odds devig/consensus builder
                              ▼
        Prediction layer (minutes · goals · assists · CS · DC · saves · bonus → xP)
                              ▼
        Optimiser (MILP: squad · transfers · captain · chips)
                    ├──────────────► Read API + React frontend
                    └──────────────► Notification service (Pushover + email)
       Offline:  Predictive-validity study  ──produces──►  versioned weight tables  ──feeds──► prediction layer
```

## A.3 Conventions

- **Three storage layers, immutable history.** Raw = verbatim timestamped source snapshots. Normalised = typed relational facts. Feature = derived model inputs. The FPL API mutates in place (prices/ownership/news), so point-in-time raw snapshots are mandatory to reconstruct "what was knowable at deadline X."
- **Stages strictly dependency-ordered and self-contained.** No stage starts before its inputs exist; no invented sub-stages.
- **Versioned weights.** The study emits weight artefacts; the live predictor loads a pinned version; rollback supported.
- **Rule-invariant first.** Predict real-match events; convert to points via the *current* scoring function (versioned, one-file edit on rule change).
- **Free-stack, role-based, multi-source odds.** No paid data vendors. Odds come from several free tiers in complementary roles so losing any one degrades coverage rather than breaking the layer. **Rate caps — not data availability — govern the odds design.**

---
---

# PART B — Datapoint catalogs & rules

## B.1 Data sources & history horizons (free stack)

| Source | Gives | Earliest | Span | Access / notes |
|---|---|---|---|---|
| Official FPL API | Players, prices, ownership, points, fixtures, FDR, entries, transfers, leagues, chips, `game_settings` (scoring) | live; archive 2016/17 | ~9 | No docs; public endpoints unauthenticated; `/my-team` needs the operator cookie; CORS-blocked → server-side; self-rate-limit. |
| vaastav/Fantasy-Premier-League | Canonical historical FPL, GW-by-GW | 2016/17 | ~9 | Backtest/history. |
| FPL-Elo-Insights / FPL-Core-Insights | Opta-like per-match stats (CBIT/CBIRT, xGOT, duels) + ClubElo + cup/Euro, aligned to FPL IDs | ~2024/25 | ~1–2 | CSV, refreshed twice daily. Clean DC feed (recent). |
| Understat | xG, npxG, xA, xGChain, xGBuildup, shot-level | 2014/15 | ~11 | Scrape; align by name/team. Deepest attacking history. |
| FBref (Opta/StatsBomb) | SCA/GCA, progressive passes/carries, duels, aerials, pressures, GK PSxG, tackles/int/blocks/clearances | 2017/18 | ~8 | Scrape, rate-limited. Enables DC reconstruction. |
| ClubElo | Daily team Elo, home/away | long | — | Free API. |
| **API-Football** (api-sports.io) **free tier** | **Lineups, injuries**, pre-match (soft) odds, fixtures, events, standings, player stats | live | — | **Free 100 req/day.** Structured lineup/injury feed (fills free-stack lineup gap). Soft books only (no Pinnacle). |
| **Betfair Exchange** (Delayed App Key) | Back/lay match + goals + goalscorer markets → devig | live | — | **Free** delayed key (1–180s delay; no traded volume; price-only). **Primary odds source.** Live key rejected (fee + betting required). |
| **SharpAPI** (sharpapi.io) free | **Pinnacle** odds + **auto no-vig fair odds**, EPL/soccer | live | — | **Free 12 req/min.** Sharp benchmark / closing-line anchor; devig done for you. |
| **Sports Game Odds** (SGO) free | EPL **player props** (goalscorer, shots, SOT) + 80+ books incl. Pinnacle | live | — | Free tier, **object-limited** (budget hard). Player-prop gap-filler. |
| **OddsPapi** (oddspapi.io) free | 350+ books incl. sharps (Pinnacle, Singbet, SBOBet) + Betfair back/lay | live | — | **Free 250 req/month.** Consensus + sharp-vs-soft + CLV. Low cap. |
| **odds-api.io** free | Multi-book odds | live | — | **Free 100 req/hour**, no card. High-volume fallback; verify book/market coverage. |
| Scraped lineups / referee | Predicted XI, referee appointments & tendencies | live | — | Fallback/supplement to API-Football; scrape-fragile, lower confidence. |
| Football-Data.org | Fixtures, results, standings, lineups | live | — | Free; **no meaningful odds** — fixtures/results backup only. |

**Rejected/avoided:** paid API-Football/Sportmonks tiers, OddsJam/OpticOdds/SportsDataIO (paid), Pinnacle's own API (account-gated), The Odds API as a dependency (free tier tightened/ambiguous across `the-odds-api.com` vs `theoddsapi.com` — keep only as an optional match-market cross-check within quota, never relied upon).

**Ragged-history rule:** maintain a feature-availability matrix; validate each feature only over the span it exists; report every finding with its `n_seasons`.

## B.2 FPL API endpoint map

| Endpoint | Contents | Cadence |
|---|---|---|
| `/bootstrap-static/` | `elements`, `teams`, `element_types`, `events`, `game_settings`, `chips`, `phases` | hourly; ↑ near deadline |
| `/fixtures/`, `/fixtures/?event={GW}` | fixtures, kickoff, FDR, `future=1` | daily; hourly near deadline |
| `/element-summary/{id}/` | per-player remaining fixtures+FDR, per-GW history, past seasons | daily; on-demand for candidates |
| `/event/{GW}/live/` | live per-player stats + provisional points + BPS | live during matches |
| `/entry/{id}/` | manager meta, leagues, rank, bank, team value | daily + post-GW |
| `/entry/{id}/history/` | GW-by-GW + past seasons + chips used | post-GW |
| `/entry/{id}/transfers/` | every transfer (in/out, cost, time) | hourly for tracked → transfer detection |
| `/entry/{id}/event/{GW}/picks/` | 15 picks, captain/vice, bench, chip | post-deadline |
| `/leagues-classic/{id}/standings/` | standings (paginated) → enumerate elites | periodic |
| `/event-status/`, `/dream-team/{GW}/`, `/set-piece-notes/` | bonus status, dream team, set-piece takers | as needed |
| `/me/`, `/my-team/{id}/` (+ cookie) | authed: own team, selling prices, bank, chips | operator only |

## B.3 Player — FPL-native fields (`elements` + element-summary)

- **Identity/meta:** id, code, first_name, second_name, web_name, team, team_code, element_type, squad_number, photo, status (a/d/i/s/u/n), special, region.
- **Price/ownership/transfers:** now_cost, now_cost_rank(_type), cost_change_event(_fall), cost_change_start(_fall), selected_by_percent, selected_rank(_type), transfers_in(_event), transfers_out(_event).
- **Availability/news:** chance_of_playing_this_round, chance_of_playing_next_round, news, news_added.
- **Scoring totals:** total_points, event_points, points_per_game(_rank,_type), dreamteam_count, in_dreamteam, bonus, bps.
- **Form/value/EP:** form(_rank,_type), value_form, value_season, ep_this, ep_next.
- **Raw counts (season + per-GW):** minutes, starts, goals_scored, assists, clean_sheets, goals_conceded, own_goals, penalties_scored, penalties_missed, penalties_saved, yellow_cards, red_cards, saves.
- **Expected (FPL-provided, 2022/23+):** expected_goals, expected_assists, expected_goal_involvements, expected_goals_conceded + per_90 of each.
- **ICT:** influence, creativity, threat, ict_index + each `_rank` and `_rank_type`.
- **Defensive contribution (2025/26+):** defensive_contribution, defensive_contribution_per_90.
- **Per-90 normalisations:** saves_per_90, clean_sheets_per_90, goals_conceded_per_90, starts_per_90.
- **Set-piece role:** corners_and_indirect_freekicks_order(+_text), direct_freekicks_order(+_text), penalties_order(+_text).
- **Per-GW history:** GW-sliced versions of the above + value (price), transfers_balance, selected, was_home, opponent_team, kickoff_time, round, fixture, team_h_score, team_a_score.
- **Past seasons:** season-by-season totals (history_past).

## B.4 Player — advanced per-match stats (FPL-Elo-Insights / Understat / FBref)

- **Time:** start_min, finish_min, minutes_played.
- **Attacking:** goals, assists, penalties_scored, penalties_missed, total_shots, shots_on_target, xg, xa, xgot, big_chances_missed, chances_created, successful_dribbles(+%), touches, touches_opposition_box, final_third_passes, accurate_crosses(+%), accurate_long_balls(+%), accurate_passes(+%).
- **Defensive (drives DC):** tackles, tackles_won(+%), interceptions, recoveries, blocks, clearances, headed_clearances, dribbled_past, duels_won, duels_lost, ground_duels_won(+%), aerial_duels_won(+%), was_fouled, fouls_committed, offsides.
- **Goalkeeping:** saves, goals_conceded, team_goals_conceded (on pitch), xgot_faced, goals_prevented (PSxG−GA), sweeper_actions, high_claim, gk_accurate_passes, gk_accurate_long_balls.
- **Understat extra:** xGChain, xGBuildup, shot-level (x/y, body part, situation, result).
- **FBref/StatsBomb extra:** progressive passes/carries, progressive passes received, SCA/GCA (with breakdowns), pressures by third, passes by length/type, carries into final third / box, miscontrols, dispossessions, GK PSxG/PSxG±, crosses stopped, defensive-action distance from goal.

## B.5 Team — match & strength

- **FPL team fields:** id, code, name, short_name, strength, strength_overall_home/_away, strength_attack_home/_away, strength_defence_home/_away, pulse_id, elo (ClubElo).
- **Per-match team stats (home/away each):** possession, expected_goals_xg, xg_open_play, xg_set_play, non_penalty_xg, xg_on_target_xgot, total_shots, shots_on/off_target, shots_inside/outside_box, blocked_shots, hit_woodwork, big_chances(+missed), passes/accurate_passes(+%), passes own/opposition half, accurate_long_balls(+%), accurate_crosses(+%), throws, touches_in_opposition_box, offsides, fouls, corners, yellow/red, tackles_won(+%), interceptions, blocks, clearances, keeper_saves, duels_won, ground_duels_won(+%), aerial_duels_won(+%), successful_dribbles(+%).

## B.6 Fixture / schedule

event(GW), kickoff_time, team_h/team_a, team_h_difficulty/team_a_difficulty (FDR), finished, started, provisional_start_time, minutes, scores; derived: own Elo+odds difficulty (attack and defence separately), double/blank GW flags, congestion (days since last match, midweek Euro/cup), travel.

## B.7 Coach / referee (free-stack: thinner, inferred + scraped)

Manager/coach: no clean tactical-style feed on the free stack — **rotation tendency inferred** from observed minutes variance + cup/Euro behaviour, supplemented by FBref squad/manager pages. Referee: appointments + tendencies (cards/game, penalties/game, fouls/game) from **scraped** previews / free referee-stats sites + any structured data API-Football's free tier exposes. All such features carry a `source=scraped|inferred` tag and **lower confidence**; they remain in the catalog but the minutes model leans primarily on FPL availability + observed minutes (B.13 shared).

## B.8 Betting-odds markets & the free multi-source layer

### B.8.1 Markets
- **Match markets (Pinnacle/Betfair/soft books):** 1X2, Asian handicap, over/under totals (2.5 etc.), BTTS, correct score, clean-sheet, winning margin.
- **Player markets:** anytime/first/last goalscorer, shots, shots on target, assists, to be carded — sourced from **SGO** (free, props) and **Betfair** goalscorer markets (liquid games).
- **Derived (the value):** **devig → true P** (win / CS / team-scores-N / player-scores); team goal-expectation from 1X2+totals; line movement / steam (open→deadline); **closing line** (sharpest near-deadline price) as the calibration benchmark.

### B.8.2 Free odds providers (roles)
| Provider | Free tier | EPL | Sharp | Props | No-vig built in | Role |
|---|---|---|---|---|---|---|
| Betfair Exchange (delayed) | free | ✓ | crowd-sharp | goalscorer (liquid) | no | **Primary** true price |
| SharpAPI | 12 req/min | ✓ | **Pinnacle** | yes | **yes** | **Sharp benchmark / closing line** |
| SGO | object-limited | ✓ | Pinnacle+80 | **goalscorer/shots/SOT** | no | **Player props** |
| OddsPapi | 250/mo | ✓ | Pinnacle/Singbet/SBOBet/Betfair | varies | no | **Consensus + CLV** |
| odds-api.io | 100/hr | ✓ (verify) | verify | verify | no | High-volume fallback |
| API-Football (free) | 100/day | ✓ | soft only | shallow | no | Soft odds + **lineups/injuries** |

### B.8.3 Consensus devig
Ingest all available sources → one **true-probability per market**, weighting the **sharpest** sources highest (Pinnacle no-vig and Betfair back/lay ≫ soft books). Sharp-vs-soft disagreement is itself a signal (steam/mispricing). Flag each consensus with `n_sources` and `sharp_present`. **Rate caps govern**: budget a consensus sweep per scheduled check, cache-first, degrade to fewer sources before exhausting any provider's free cap.

## B.9 Elite-manager / smart-money

Enumerate via top-1% / top-10% global leagues and high-finish public leagues → store entry_ids. Per manager per GW: 15 picks, captain/vice, bench order, chip, transfers, hits, team value, bank, rank trajectory. Aggregate: elite-cohort effective ownership (≠ global EO), elite captaincy %, net transfer flow, template-vs-differential map.

## B.10 The 2025/26 FPL ruleset

**Squad:** 15 = 2 GK / 5 DEF / 5 MID / 3 FWD; **£100.0m** budget; **max 3 per club**; valid XI (1 GK; 3–5 DEF; 2–5 MID; 1–3 FWD); captain ×2 + vice.

**Base scoring:**

| Event | GK | DEF | MID | FWD |
|---|---|---|---|---|
| 1–59 / 60+ min | 1 / 2 | 1 / 2 | 1 / 2 | 1 / 2 |
| Goal | 6 | 6 | 5 | 4 |
| Assist | 3 | 3 | 3 | 3 |
| Clean sheet | 4 | 4 | 1 | 0 |
| 3 saves | 1 | — | — | — |
| Penalty save / miss | 5 / −2 | −2 | −2 | −2 |
| 2 goals conceded | −1 | −1 | — | — |
| Yellow / Red | −1 / −3 | −1 / −3 | −1 / −3 | −1 / −3 |
| Own goal | −2 | −2 | −2 | −2 |
| **Defensive contribution** | — | **+2 @ CBIT≥10** | **+2 @ CBIRT≥12** | **+2 @ CBIRT≥12** |
| Bonus (BPS top-3) | 1–3 | 1–3 | 1–3 | 1–3 |

- **DC:** DEF +2 for ≥10 Clearances+Blocks+Interceptions+Tackles; MID/FWD +2 for ≥12 CBIT + ball Recoveries (CBIRT). Single +2 threshold. GKs ineligible.
- **Assist (2025/26):** counts if goalscorer received in the box with ≤1 defensive touch between; intended-destination no longer required.
- **BPS:** tackles-lost no longer penalised.
- **Transfers:** 1 free/GW, **bankable up to 5**; extra = **−4** each. Sell value = purchase + half the rise (rounded).
- **Chips (two full sets):** Wildcard, Free Hit, Triple Captain, Bench Boost — each **twice**, once per half (GW1–19, GW20–38). **First set expires at GW19 deadline (18:30 GMT, 30 Dec 2025); no carryover.** **Assistant Manager chip removed.**
- **AFCON:** all managers get **5 free transfers in GW16**; model AFCON absences explicitly.
- **Other:** elite global leagues (top-1% / top-10%); detect double/blank GWs from the fixture feed.

## B.11 The window bank (GW-count)

- Short: last 3, 5, 8 GWs. Medium: last 12, 19 GWs. Long: last 38 GWs, last 2 seasons, career.
- EWMA half-lives: 2, 5, 10, 20 GWs.
- Representations: (a) multi-window levels; (b) **level(38) + momentum [short − long]**.
- Windows computed over each player's **appearance sequence** (skill travels with matches, not calendar dates).

## B.12 Rule-invariant target → current-rules conversion

Predict each component (rate/per-90 or probability), gate by minutes, then `Σ(component × current point value) + E(bonus)`:

| Component | GK | DEF | MID | FWD |
|---|---|---|---|---|
| Appearance | ✓ | ✓ | ✓ | ✓ |
| Goal (6/6/5/4) | ✓ | ✓ | ✓ | ✓ |
| Assist (3) | ✓ | ✓ | ✓ | ✓ |
| Clean sheet (4/4/1/0) | ✓ | ✓ | ✓ | — |
| Saves (1/3) | ✓ | — | — | — |
| DC threshold (+2) | — | ✓ | ✓ | ✓ |
| Pen save/miss, conceded, cards, OG | ✓ | ✓ | ✓ | ✓ |
| Bonus (sub-model) | ✓ | ✓ | ✓ | ✓ |

GKs earn no DC. Converter is versioned (one-file edit on rule change).

## B.13 Per-position feature families (Phase-1, stats-only)

Sources: FPL basic (9), Understat (11), FBref (8), reconstructed DC (8), ClubElo. All carry the §B.11 window bank. Odds/market features excluded here (added Phase 7). `n` = validatable seasons.

### Shared — Minutes/availability (multiplies into every component)
| Family | Features | Span |
|---|---|---|
| Recent role | starts rate (3/5/8), minutes/appearance, sub-on/off rate, minutes variance | 8–9 |
| Declared availability | chance_of_playing_next_round, status, news recency | 9 |
| Congestion | days since last match, midweek Euro/cup in window, fixtures-next-N | feed |
| Team context | squad minutes concentration, likely-rotation-spot flag | 8–9 |

### GK — CS (team) vs saves (workload), modelled separately
| Family | Component | Features | Span |
|---|---|---|---|
| Team defence | CS, conceded | team xGA/90, team Elo (def), goals conceded, SoT faced/90 | 11/—/8 |
| Opponent attack | CS, conceded | opp xG-for/90, opp shots/SoT, opp Elo (att), home/away | 11/— |
| Shot-stopping | saves, conceded | **PSxG−GA (goals prevented)**, save %, PSxG faced/90 | 8 |
| Workload | saves | SoT faced/90 (busy keeper → saves floor) | 8 |
| Pens/set play | saves, conceded | pen-save rate (low-n), set-piece xGA | 8 |

### DEF — CS, DC (CBIT≥10), attacking returns (DC vs normalised target)
| Family | Component | Features | Span |
|---|---|---|---|
| CS drivers | CS, conceded | team xGA/90, opp xG-for, Elo, home/away | 11/— |
| **DC / CBIT** | DC | tackles+interceptions+blocks+clearances/90; **CBIT≥10 hit-rate**; headed clearances | 8 |
| Attacking threat | goals, assists | xG90, npxG90, xA90, key passes, crosses, touches in box, shots/90 | 11/8 |
| Set-piece/pen role | goals, assists | penalties_order, FK/corner duty | 9 |
| Aerial/duel | bonus, conceded | aerial duels won/90, duels won % | 8 |
| Bonus drivers | bonus | BPS-positive actions, historical BPS rate | 8 |

### MID — attacking, DC (CBIRT≥12), 1-pt CS; highest variance → short windows matter most
| Family | Component | Features | Span |
|---|---|---|---|
| Goal threat | goals | xG90, npxG90, shots/90, shots in box, big chances, xGOT | 11/8 |
| Creation | assists | xA90, key passes/90, SCA/GCA/90, **xGChain/xGBuildup** | 11/8 |
| Set-piece/pen role | goals, assists | penalties order, FK/corner duty | 9 |
| **DC / CBIRT** | DC | CBIT + recoveries /90; **CBIRT≥12 hit-rate** | 8 (recoveries noisy pre-2024) |
| Progression | goals, assists, minutes | progressive passes/carries/90, final-third entries, touches | 8 |
| Team attack context | goals, assists | on-pitch team xG share, team xG-for, opp xGA, fixture ease | 11/— |

### FWD — goals/assists; predict from underlying xG; goals−xG = mean-reversion
| Family | Component | Features | Span |
|---|---|---|---|
| Finishing vol/quality | goals | npxG90, xG90, shots/90, **xG per shot**, % shots in box, big chances, xGOT | 11/8 |
| Mean-reversion | goals | (goals − xG) over window → expected **negative** weight | 8–11 |
| Penalty role | goals | penalties order, historical pen share (high value) | 9 |
| Creation | assists | xA90, key passes, xGBuildup | 11/8 |
| Team/fixture | goals, assists | team xG-for/90, opp xGA, Elo, home/away | 11/— |
| DC (minor) | DC | CBIRT≥12 hit-rate (rare for FWD) | 8 |

### DC reconstruction (FBref → 2017/18)
CBIT (DEF) = tackles+interceptions+blocks+clearances per match → `≥10`. CBIRT (MID/FWD) = CBIT+recoveries → `≥12`. Recoveries inconsistent pre-2024 → `recoveries_imputed` flag, reduced confidence for MID/FWD; CBIT clean back to 2017/18. Validate against the clean DC feed (2024/25+) on the overlap before trusting backfill.

---
---

# PART C — Model & optimiser specs

## C.1 xP prediction (component-wise, bottom-up)

```
xP = P(plays) × [ appearance_pts
                + goal_pts   × E(goals)
                + assist_pts × E(assists)
                + CS_pts     × P(clean sheet | 60+)
                + DC_pts     × P(CBIT/CBIRT threshold)
                + saves/pen/card/conceded terms
                + E(bonus) ]
captain ×2 (×3 Triple Captain)
```

Sub-models: **(1) Minutes** → P(plays), P(60+), E(minutes) — highest leverage; leans on FPL availability + observed minutes + congestion + API-Football lineups. **(2) Attacking** → own xG90/xA90 blended with fixture, anchored to odds anytime-scorer where available (Phase 7). **(3) Clean sheet** → team def xGC + opp att + odds-implied CS. **(4) DC** → per-player CBIT/CBIRT distribution → P(threshold). **(5) Bonus** → predict BPS → P(top-3). **(6) Calibration** → vs realised + sharp closing line, per position. Fixture difficulty = Elo+odds blend, separate for attack vs defence.

## C.2 Optimiser (MILP)

- **(a) Squad/XI:** maximise starting-XI xP s.t. budget, 2/5/5/3, max-3-per-club, valid formation, captain multiplier; bench discounted by P(needed)×xP.
- **(b) Multi-GW transfer plan:** maximise cumulative xP over an N-GW horizon (**configurable 5–8, default 6**) **net of −4 hits**, respecting FT accrual (bankable to 5), price changes, chip windows (two-half, GW19 expiry, GW16 five-FT AFCON), AFCON absences. Output transfer path + per-week captain + chip-timing suggestion.
- **Captaincy:** max single-GW xP; for Triple Captain weight an upside percentile (ceiling), not the mean.
- **Risk/EO overlay:** blend pure xP with elite-cohort effective ownership along a tunable "protect-rank ↔ chase-rank" axis.

---
---

# PART D — Phased build

**Phase dependency graph:**
```
P0 Foundations
      │
P1 Historical lake ─► P2 Targets/DC ─► P3 Features ─► P4 Study v1 (weights frozen)
      │                                                   │
P5 Live data plane ───────────────────────────────────►  P6 Prediction service
                                                          │            │
                                          P7 Market integration (v2) ◄─┘
                                                          │
P6/P7 ─► P8 Optimiser ─► P9 Tracking/recs/notifications
                                   │
P1+P8+P6 ─► P10 Backtester & app layer
```
Each stage: **Depends · Instructions · Datapoints · Output · Done.**

## PHASE 0 — Foundations

**0.1 — Repo, environments, config/secrets.** Depends: none. Instructions: scaffold the monolith (ingest / store / features / model / optimise / api / notify); per-env config; **secrets vault holding FPL session cookie + all odds-API keys (SharpAPI/SGO/OddsPapi/odds-api.io/API-Football) + Betfair credentials/app key**. Datapoints: none. Output: skeleton + CI. Done: CI green; secrets loadable, never logged.

**0.2 — Database & three-layer schema.** Depends: 0.1. Instructions: Postgres + TimescaleDB; RAW/NORMALISED/FEATURE schemas; migrations; partition time-series by season. Output: migratable DB. Done: migrate up/down clean; hypertables created.

**0.3 — Shared rate-limited fetch/ingest framework.** Depends: 0.2. Instructions: one fetch layer — real UA, **per-provider rate limits + monthly/daily/per-minute budget counters**, exponential back-off on 429, caching, raw-snapshot write-through, idempotency. Output: `fetch()` + `snapshot()` + `budget()`. Done: simulated 429 backs off; budget counter blocks before a free cap is exceeded; re-runs don't duplicate raw rows.

**0.4 — Scheduler/orchestrator + observability.** Depends: 0.3. Instructions: cron-like + event triggers; run registry; structured logging; failure alerting; **per-provider consumption dashboard**. Output: orchestrator. Done: a no-op job runs, logs, registers; consumption visible.

## PHASE 1 — Historical data lake

**1.1 — Historical acquisition.** Depends: 0.4. Instructions: pull all available seasons — vaastav FPL (2016/17+), Understat (2014/15+), FBref (2017/18+), ClubElo — into RAW verbatim, timestamped. Datapoints: §B.3–B.6 historical. Output: populated RAW. Done: every season stored; re-pull idempotent; coverage report.

**1.2 — Cross-source entity resolution.** Depends: 1.1. Instructions: player/team crosswalk (FPL id ↔ Understat name/team ↔ FBref id) via deterministic + fuzzy + manual-override table. Datapoints: identity fields. Output: `id_crosswalk`. Done: ≥99% of player-seasons with FPL minutes mapped; unmatched reviewed.

**1.3 — Normalised per-match fact tables.** Depends: 1.2. Instructions: unified `player_match_stats` + `team_match_stats` keyed by canonical IDs, merging sources field-by-field. Datapoints: §B.4, B.5. Output: NORMALISED layer. Done: row counts reconcile; spot-checks pass.

## PHASE 2 — Targets & defensive reconstruction

**2.1 — DC reconstruction (FBref → 2017/18).** Depends: 1.3. Instructions: per §B.13 reconstruction; validate vs clean DC feed on overlap. Datapoints: §B.4 defensive. Output: `dc_match`. Done: matches clean feed within tolerance on overlap.

**2.2 — Rule-invariant targets + current-rules converter.** Depends: 2.1. Instructions: build forward component outcomes; versioned converter (§B.12) → `normalised_points` + `as_played_points`. Datapoints: §B.10, B.12. Output: `targets`. Done: converter reproduces actual 2024/25 & 2025/26 points from actual events within rounding.

## PHASE 3 — Feature engineering

**3.1 — Availability matrix + walk-forward panel.** Depends: 2.2. Instructions: `feature_availability`; strictly-causal `training_rows` (player × deadline × horizon {1, 6, rest-of-season}; trailing data only). Output: `training_rows`. Done: leakage audit passes; spans all seasons.

**3.2 — Windowing engine.** Depends: 3.1. Instructions: apply §B.11 bank over each player's appearance sequence. Output: windowed features. Done: unit-tested on synthetic sequences incl. injury gaps.

**3.3 — Per-position feature assembly (Phase 1).** Depends: 3.2. Instructions: assemble §B.13 families per position, Phase-1 sources only; span-tag each. Output: per-position matrices. Done: every family present with correct span tags.

## PHASE 4 — Predictive-validity study (stats-only → v1 weights)

**4.1 — Predictive-validity analysis.** Depends: 3.3. Instructions: per position × component × horizon — univariate rank-IC screen with **FDR correction** → Elastic-Net weights → LightGBM + SHAP; **leave-one-season-out CV**; **beat-the-baseline gate** (last-GW, season PPG, FPL ep_next); family-level grouping; sign/IC stability required. Output: `feature_importance` (weight, window, half_life, mean/σ IC, n_seasons, FDR-q). Done: weights per position/component/horizon; stability reported.

**4.2 — Shrinkage calibration + holdout → freeze v1.** Depends: 4.1. Instructions: fit empirical-Bayes prior strength per metric/position (short↔long blend); validate on untouched final season; freeze v1. Output: calibrated weights + half-lives + `model_calibration`; `model_registry` v1. Done: holdout metrics recorded; v1 frozen.

## PHASE 5 — Live data plane

**5.1 — FPL live ingestion (+ auth).** Depends: 0.4. Instructions: scheduled pulls of bootstrap-static, fixtures, element-summary, event/live, game-settings per §B.2 → RAW → NORMALISED current-state; use the **operator cookie** for `/me/` + `/my-team/{id}` (selling prices, bank); on auth failure fall back to public endpoints + manual team-value + raise "re-auth needed". Datapoints: §B.3–B.6, B.9. Output: live FPL tables. Done: a full GW cycle ingests; authed selling prices read; cookie never logged.

**5.2 — Entry/manager + league + elite cohort.** Depends: 5.1. Instructions: ingest entry/history/transfers/picks; enumerate elites (top-1%/top-10% + high-finish public); store cohort. Datapoints: §B.9. Output: manager tables + cohort. Done: cohort built; per-GW picks captured post-deadline.

**5.3 — Multi-source odds layer.** Depends: 0.4. Instructions: one isolated ingestor per provider on the shared fetch/budget framework — **Betfair Exchange (delayed)** primary; **SharpAPI** (Pinnacle no-vig); **SGO** (player props); **OddsPapi** (consensus); **odds-api.io** (fallback); API-Football soft odds opportunistically. Normalise each → common `odds_snapshots` (event, market, selection, source, price/back/lay, no_vig_prob?, captured_at). Build the **devig/consensus** builder (§B.8.3) → `true_probabilities` (source-weighted, `n_sources`, `sharp_present`); capture line movement open→deadline. Budget-aware: cache-first, degrade to fewer sources before any free cap. Datapoints: §B.8. Output: `odds_snapshots` + `true_probabilities`. Done: consensus probabilities produced for match markets and (where available) props from ≥2 independent free sources without exceeding any quota; sharp presence flagged.

**5.4 — Lineups / injuries / news / referees.** Depends: 5.1. Instructions: **API-Football free tier (100/day)** as the structured **lineups + injuries** feed (predicted + confirmed); scraped lineup aggregators as fallback; FPL `news`/`status` parsing; scraped referee appointments + tendencies. Each isolated ingestor; `source` tagged. Datapoints: §B.7 + availability fields. Output: lineup/injury/referee tables. Done: a status flip and a lineup confirmation are detected and timestamped within budget.

## PHASE 6 — Prediction service

**6.1 — Minutes/availability model (live).** Depends: 4.2, 5.4. Instructions: serve P(start)/P(60+)/E(minutes) from the shared minutes family + live availability/lineups/congestion. Output: minutes predictions. Done: calibrated on holdout; updates on lineup confirmation.

**6.2 — Component xP predictor (v1 weights).** Depends: 6.1. Instructions: implement §C.1 components (goals/assists/CS/DC/saves/bonus) consuming frozen v1 weights + windowed live features. Output: per-component predictions. Done: each component calibrated vs realised on holdout.

**6.3 — Fixture difficulty + per-GW xP assembly.** Depends: 6.2, 5.3. Instructions: Elo+odds blended difficulty (attack vs defence separately); assemble components → per-player per-GW xP with breakdown. Output: `predictions_player_gw`. Done: xP produced for current GW with stored component breakdown.

## PHASE 7 — Market integration (study Phase 2 → v2 weights)

**7.1 — Odds feature block + re-screen + beat-the-market gate.** Depends: 4.2 (frozen v1), 5.3, 6.3. Instructions: derive features from consensus `true_probabilities` (P(CS), P(team scores 0/1/2/3+), P(anytime scorer — SGO/Betfair), team goal-expectation, steam/line-movement); add as a block; **re-screen against frozen v1 — keep only features adding incremental out-of-sample skill**; apply **beat-the-market gate vs the sharpest near-deadline consensus** (Pinnacle no-vig / Betfair). Tag props `source=sgo|betfair, liquidity_limited`, ~3-season span. Output: weights v2 + market-skill diagnostics; dropped-feature log. Done: each market feature earns incremental skill or is dropped (logged); closing-line calibration recorded.

**7.2 — Publish weights + refit cadence.** Depends: 7.1. Instructions: wire v2 into the live predictor; schedule refits — full pre-season; lightweight at GW19 checkpoint / any rule change; minutes-model re-validation around AFCON/congestion. Output: live predictor on versioned weights. Done: end-to-end xP from published weights; rollback to a prior `model_registry` version works.

## PHASE 8 — Optimiser

**8.1 — Squad/XI selection MILP.** Depends: 6.3 (or 7.2). Instructions: §C.2(a) — budget, 2/5/5/3, max-3-per-club, valid formation, captain ×2, discounted bench. Output: optimal squad/XI. Done: valid squad maximising XI xP; constraints provably respected.

**8.2 — Multi-GW transfer planner.** Depends: 8.1. Instructions: §C.2(b) — **horizon configurable 5–8, default 6**, −4 hits, FT accrual to 5, price changes, AFCON absences. Output: transfer path + weekly XI. Done: beats a greedy one-week baseline on backtest xP-net-of-hits.

**8.3 — Captaincy + chip timing.** Depends: 8.2. Instructions: captain = max single-GW xP (upside percentile for TC); optimise chips across two halves respecting GW19 expiry + GW16 AFCON 5-FT. Output: captain + chip schedule. Done: chip windows/expiry enforced; TC targets ceiling.

**8.4 — Risk/EO overlay.** Depends: 8.3, 5.2. Instructions: blend xP with elite-cohort effective ownership along a tunable rank-protect↔chase axis. Output: EO-aware recommendations. Done: knob shifts differential↔template as expected.

## PHASE 9 — Tracking, recommendations & delivery

**9.1 — Tracked-team ingestion + transfer detection.** Depends: 5.2. Instructions: poll `/entry/{id}/transfers/` + `/picks/`; diff vs last known → emit "transfer detected"; use authed selling price/bank from 5.1. Output: tracked-team state + events. Done: a real transfer is detected and logged; team value exact.

**9.2 — Recommendation generation.** Depends: 9.1, 8.4. Instructions: run optimiser against the *current* tracked roster → transfers/captain/chips with rationale (component breakdown + EV). Output: `recommendations`. Done: a recommendation with rationale for the upcoming deadline.

**9.3 — Continuous trigger orchestration.** Depends: 9.2, 5.1, 5.3, 5.4. Instructions: triggers — price-change watch (~01:30 UK), news/lineup watch, odds steam, post-match recompute (provisional→confirmed bonus); re-score on trigger. Output: trigger pipeline. Done: each trigger type fires a recompute in test.

**9.4 — Notification service (Pushover + email).** Depends: 9.3. Instructions: **two channels, both active by default — Pushover and email (SMTP)**; notify on recommended transfer, captain (+alt), price-risk on owned, injury/red-flag on owned, deadline, chip-window prompt; per-channel + per-type enable/disable + EV/confidence thresholds. Email carries fuller rationale (component breakdown, EV); Pushover concise action + link. Output: notifications. Done: a threshold-crossing recommendation delivers on **both** channels; sub-threshold stays silent on both.

## PHASE 10 — Backtester & app layer

**10.1 — Strategy backtester.** Depends: 1.3, 8.4, 6.3. Instructions: replay seasons GW-by-GW using only-then-knowable data; run predict→optimise→transact; score season points vs baselines (always-template, season-PPG greedy, FPL ep_next greedy). Strictly causal. **Odds-inclusive backtest bounded by available historical odds** (Betfair Historical Data Service / what's obtainable); **pre-feed seasons run stats-only** (benign — Phase 4 is stats-only by design). Output: backtest reports. Done: reproduces a known season within tolerance; reports edge over baselines.

**10.2 — Read API + frontend.** Depends: 9.4, 10.1. Instructions: read API over predictions/recommendations/backtests; React dashboards (player xP + breakdown, fixture difficulty, transfer planner, tracked-team view, elite-cohort EO, backtest results). Output: API + UI. Done: operator can view xP, recommendations, and a backtest end-to-end.

---
---

# PART E — Data model, glossary, decisions, risks

## E.1 Data model

- **Reference/facts:** teams, players, coaches, referees, fixtures, matches(+match_team_stats), player_match_stats, dc_match, player_gw_snapshots, gameweeks, chips_state.
- **Odds/managers:** odds_snapshots, true_probabilities, managers (tracked + elite), manager_gw_picks, manager_transfers.
- **Study:** feature_availability, training_rows, feature_importance, model_calibration, model_registry.
- **Serving:** features_player_gw, predictions_player_gw, recommendations, backtest_runs.
- All source-mutating entities carry point-in-time snapshot history.

## E.2 Glossary

CBIT = Clearances+Blocks+Interceptions+Tackles. CBIRT = CBIT+Recoveries. xG/xA = expected goals/assists. npxG = non-penalty xG. xGOT = xG on target. PSxG = post-shot xG (goals_prevented = PSxG−GA). SCA/GCA = shot-/goal-creating actions. EWMA = exponentially-weighted moving average. IC = information coefficient. LOSO = leave-one-season-out. EO = effective ownership. Devig / no-vig = removing bookmaker margin to recover true probability. CLV = closing-line value. FT = free transfer. TC/BB/WC/FH = Triple Captain / Bench Boost / Wildcard / Free Hit.

## E.3 Locked decisions (no open items)

1. **Data:** free stack only (FPL + Understat + FBref + FPL-Elo-Insights + ClubElo + API-Football free tier + free odds APIs). No paid vendors.
2. **Odds:** Betfair Exchange (Delayed App Key) primary; SharpAPI (Pinnacle no-vig) sharp benchmark; SGO player props; OddsPapi consensus; odds-api.io fallback; consensus devig weighting sharp sources highest.
3. **Lineups/injuries:** API-Football free tier (structured) + scraped fallback; referee/coach thin & scraped/inferred.
4. **Optimiser horizon:** 5–8 GW, default 6.
5. **Notifications:** Pushover + email.
6. **Auth:** store operator FPL session cookie for `/my-team`.
7. **Target:** rule-invariant components → current-rules converter (versioned).
8. **Windows:** GW-count; four FPL positions only; DC reconstructed from FBref to 2017/18; Phase-1 stats-only, odds in Phase 7.

*Confirm-at-signup (terms volatility, not decisions): each free odds tier's current allowance and book/market coverage.*

## E.4 Standing risks

- **Overfitting** (thousands of features × ~9 seasons) — primary failure mode; mitigated by FDR correction, family-level selection, LOSO-CV, shrinkage, untouched holdout (Phase 4). Catalog broad; live model lean.
- **Free-tier volatility** — odds providers change free allowances often; the role-based multi-source layer means losing one degrades coverage, not breaks it. **Rate caps, not coverage, govern the odds design.**
- **Free-stack thinness** — referee/coach features lower-confidence (scraped/inferred); minutes model leans on FPL availability + API-Football lineups.
- **Historical odds gap** — deep historical odds aren't on free live tiers; pre-feed seasons are stats-only in backtest (benign).
- **Rule drift** — the versioned converter (2.2) + refit cadence (7.2) absorb future scoring changes.
- **Source fragility/ToS** — scraped sources + unofficial FPL API need polite rate-limiting + caching (0.3); a source change breaks one isolated ingestor, not the model (raw layer + versioned weights isolate blast radius); free tiers assumed personal/non-commercial use.
