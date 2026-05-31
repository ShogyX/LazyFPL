# Handoff: LazyFPL "Broadcast" UI Redesign

## Overview
A full visual + interaction redesign of the LazyFPL dashboard (Team Planner, Model
Performance, Settings) in a **dark-first, sports-broadcast aesthetic**: deep-ink
backgrounds, neon data-viz, scoreboard typography, and a lot of small motion
(count-ups, charts that draw in, players settling into the pitch, a live ticker).
It keeps the existing three-page information architecture and the FPL-style pitch,
but rebuilds the look, the component kit, the charts, and the micro-interactions,
and reorganizes Model Performance around **easy side-by-side comparison** and
**progressive disclosure** (the headline answer up front, detail on hover/click).

The redesign is light/dark themeable and ships a **Tweaks** panel for accent hue,
density, and motion.

---

## About the Design Files
The files in `design_reference/` are a **design reference built in HTML + a tiny
React-via-Babel runtime** — a working prototype that shows the intended look,
layout, and behavior. **They are not meant to be dropped into the app as-is.**

Your task is to **recreate this design inside the existing LazyFPL frontend**
(`frontend/`, which is **React 18 + Vite + TypeScript + Tailwind CSS + Recharts +
lucide-react + React Router + TanStack Query**) using that codebase's established
patterns, and to **wire it to the real read API** via the existing
`frontend/src/lib/api.ts` client (do **not** keep the prototype's mock `data.js`).

The prototype deliberately mirrors the repo's structure so the port is mostly 1:1:

| Prototype file (`design_reference/`) | Maps to in `frontend/src/` |
|---|---|
| `app/theme.css` (CSS-var tokens) | `index.css` + `tailwind.config.js` |
| `app/components.jsx` | `components/ui.tsx` (+ new primitives) |
| `app/charts.jsx` | new `components/charts/*` **or** restyled Recharts |
| `app/pitch.jsx` | `components/Pitch.tsx` + `components/PlayerAvatar.tsx` |
| `app/planner.jsx` | `pages/TeamPlanner.tsx` |
| `app/performance.jsx` | `pages/ModelPerformance.tsx` |
| `app/settings.jsx` | `pages/Settings.tsx` |
| `app/main.jsx` | `components/Layout.tsx` + `App.tsx` |
| `app/tweaks-panel.jsx` | optional dev-only panel, or fold into Settings |

> The prototype uses inline `style={{…}}` + a handful of CSS classes because it has
> no build step. **In the app, prefer Tailwind utility classes** mapped to the
> tokens below (the repo already drives Tailwind from CSS variables — keep that).

---

## Fidelity
**High-fidelity.** Colors, typography, spacing, radii, motion, and interactions are
final. Recreate the UI to match — exact hex/token values are listed under
**Design Tokens**. Where the prototype invents data the current API doesn't expose
(see **Data Mapping**), implement the visual treatment and either compute the value
client-side or note it as a backend follow-up — don't drop the UI element silently.

---

## Tech & Fonts
- **Fonts:** `Archivo` (400/500/600/700/800/900) for everything incl. big numbers;
  `JetBrains Mono` (400/500/700) for tabular/stat values and axis labels. (Replaces
  the current Fira Sans / Fira Code.) Add both via the same mechanism the repo uses
  for fonts; all numeric displays use `font-variant-numeric: tabular-nums`.
- **Icons:** the prototype hand-rolls an SVG icon set (`Icon` in `components.jsx`)
  to avoid a dependency in the no-build prototype. **In the app, use the existing
  `lucide-react`** — equivalents: `bolt→Zap`, `pitch→LayoutGrid/ Goal`,
  `chart→BarChart3`, `gear→Settings`, `crown→Crown`, `swap→ArrowRightLeft`,
  `spark→Sparkles`, `target→Target`, `shield→Shield`, `flame→Flame`, `clock→Clock`,
  `search→Search`, `up/down→ArrowUp/ArrowDown`, `chevR/chevD→ChevronRight/Down`,
  `check→Check`, `info→Info`, `sun→Sun`, `moon→Moon`.
- **Charts:** the prototype hand-builds animated SVG charts (`charts.jsx`) for full
  control over the draw-in animation and neon styling. You have two options:
  1. **Port the SVG charts** (recommended for the exact draw-in feel) as small TSX
     components — they're framework-light and already typed-ish.
  2. **Keep Recharts** and restyle it with the tokens (set `stroke`/`fill` to the
     series vars, `CartesianGrid stroke=var(--line)`, themed `Tooltip`). You lose
     the custom dash draw-in but gain less code. If you keep Recharts, still add the
     **count-ups** and **hover-crosshair tooltips**.

---

## Design Tokens

All colors are CSS variables so dark/light swap without touching markup (the repo
already does this — extend it). Source of truth: `design_reference/app/theme.css`.

### Core palette — DARK (default)
```
--ink-0:    #070a10   /* page base (behind everything) */
--ink-1:    #0a0e16   /* page gradient top */
--surface:  #0f151f   /* card background */
--surface-2:#141d2a   /* insets, chips, inputs */
--surface-3:#1b2638   /* hover / elevated / tooltips */
--line:     rgba(255,255,255,0.075)   /* hairline borders */
--line-2:   rgba(255,255,255,0.14)    /* stronger borders / hover */
--fg:       #eaf1f9   /* primary text */
--fg-dim:   #97a6ba   /* secondary text */
--fg-faint: #5d6b80   /* labels / axis / tertiary */
--bad:      #ff5d6c
--warn:     #ffc24b
--pitch-a:  #15663b   /* pitch mow stripe A */
--pitch-b:  #0f5733   /* pitch mow stripe B */
```

### Core palette — LIGHT
```
--ink-0:#eaeef5  --ink-1:#e3e9f2  --surface:#ffffff  --surface-2:#f4f7fb  --surface-3:#eaeff7
--line:rgba(16,24,38,0.10)  --line-2:rgba(16,24,38,0.18)
--fg:#0e1622  --fg-dim:#51607a  --fg-faint:#8392a8
--bad:#e23744  --warn:#c9851a  --pitch-a:#2e9d5b  --pitch-b:#258a4e
```

### Accent (single hue, themeable)
The accent is derived from **one hue** via `oklch` so all accent shades stay
harmonious. A Tweak sets `--accent-h`. Default hue = **152 (electric green)**.
```
DARK:  --accent: oklch(0.82 0.17 var(--accent-h));   --accent-deep: oklch(0.66 0.17 H);
       --accent-ink: oklch(0.18 0.05 H);             /* text/icon ON accent fills */
       --accent-glow: oklch(0.82 0.17 H / 0.30);     --accent-faint: oklch(0.82 0.17 H / 0.12);
LIGHT: --accent: oklch(0.60 0.17 var(--accent-h));   --accent-ink: #ffffff; (others scale down)
```
Tweak hue presets: green 152 · cyan 196 · violet 285 · magenta 338 · coral 32 · amber 74.

### Data-series palette (fixed, independent of accent — keeps multi-series charts legible)
```
DARK:  --s0 #1fe089  --s1 #2ed3ec  --s2 #9a86ff  --s3 #ffc24b  --s4 #ff7d5c  --s5 #ff5c93
LIGHT: --s0 #0bb86d  --s1 #0fa6c4  --s2 #6a5cf0  --s3 #d99412  --s4 #e0603a  --s5 #dc3b7e
```
`--s0` is the green that matches the default accent; series cycle s0→s5.

### Radii / spacing / shadow
```
--radius: 14px   --radius-sm: 9px   chips/pills: 999px   tags: 6px
--pad: calc(20px * --dens)   --gap: calc(16px * --dens)   (card padding / grid gap)
--shadow (dark): 0 18px 50px -24px rgba(0,0,0,.85)
--shadow (light):0 16px 40px -22px rgba(16,30,54,.34)
content max-width: 1360px, centered
sidebar width: 248px
```

### Density & motion (Tweaks)
```
--dens:   compact 0.9 | regular 1 | comfy 1.12   (multiplies font-size, --pad, --gap)
--motion: full 1 | calm 0.55 | off 0.001         (multiplies every transition/animation duration)
prefers-reduced-motion → --motion forced ~0.
```

### Type scale (Archivo)
```
Page H1:        clamp(22px,3vw,30px), 800, -0.025em
Card title:     13px, 700, uppercase, +0.02em, color --fg-dim   (".card-h h2")
Eyebrow/label:  10.5px, 700, uppercase, +0.14em, color --fg-faint
Big stat:       clamp(22px,2.6vw,30px) (hero clamp(28px,4vw,40px)), 800, -0.02em, tnum
Body:           ~15px * --dens
Small/meta:     11–13px
```

---

## Global Layout (shell)

`App` → CSS grid `grid-template-columns: 248px minmax(0,1fr)`.

- **Sidebar** (`<aside>`, 248px, sticky full-height, gradient surface bg, right
  hairline): brand lockup (Zap glyph in an accent rounded square + "LazyFPL" /
  "Intelligence Engine" eyebrow) → vertical nav (Team Planner, Model Performance,
  Settings) → bottom "Auto-refresh on" status card (pulsing accent dot + copy).
  Active nav item: `--surface-2` bg, `--line` border, accent icon, small accent dot
  on the right. Hover: `--surface-2` bg.
- **Main column** (flex column): sticky **Topbar** + scrollable **content**.
- **Topbar** (sticky, 54px, `color-mix(--surface 55%, --ink-0)` solid bg, bottom
  hairline): GW deadline **countdown** (updates every second, seconds in accent) ·
  **live ticker** (see below) · theme toggle button (Sun/Moon).
- **Content**: `padding: calc(22px*--dens)`, `max-width:1360px`, centered.

**Responsive:** ≤1080px the two-column page grids collapse to one column; ≤880px the
sidebar becomes a horizontal top strip (icon-only nav, status card hidden, deadline
eyebrow hidden); ≤560px tighter padding.

> ⚠️ **Do NOT use `backdrop-filter` on the sidebar/topbar.** The prototype originally
> did and it caused black-rendering under screenshot/compositing. Use solid /
> `color-mix` backgrounds (as in the final `theme.css`). Glass blur is fine on small
> transient overlays only.

### Live ticker
Horizontal auto-scroll (CSS `@keyframes tickscroll` translateX 0→-50% over ~46s,
content duplicated for seamless loop, **pause on hover**, edge mask-image fade).
Item kinds: **live/ft score** (team badge + score + minute, live items show a
blinking red dot), **price move** (up/down arrow + name + new price + delta), **news**
(amber dot + name + note). Data source in app: derive from `api.predictions`
status/news + fixtures, or a small `/ticker` endpoint; the prototype hardcodes a
representative set.

---

## Screens

### 1) Team Planner — `pages/TeamPlanner.tsx`
**Purpose:** see your squad, who to captain, the best transfer, and chip timing —
each as a glanceable answer you can drill into.

**Layout:** vertical stack:
1. **Team header card** — brand chip + team name + "Gameweek N · season · entry id",
   and a right-aligned KPI row (count-ups): Total points · GW points (with ▲ delta) ·
   Overall rank (+ "top x%") · **Live XI projection** (accent).
2. **Two-column grid** `minmax(0,1.55fr) minmax(320px,1fr)` (stacks ≤1080px):
   - **Left — pitch card.** Header has a segmented toggle **Your team / Model XI**.
     Body shows a stat row (Projected XI xP [accent, count-up] · Formation · Squad
     value/XI cost · In the bank) then the **Pitch**, then a hint line.
   - **Right — insight rail**: Captain card, Transfer card, Chip-strategy card —
     **unless a player is selected**, in which case the rail is replaced by the
     **Player detail** drawer (Back button restores the cards).

**Pitch** (`components/Pitch.tsx`): broadcast field — mow stripes
(`repeating-linear-gradient` of `--pitch-a`/`--pitch-b`), top/bottom lighting
gradients, SVG markings (box, center circle), rows by position (GK/DEF/MID/FWD).
Each player = circular **kit avatar** (team-kit fill, collar arc, 3-letter name,
position-colored ring: GK `--s3`, DEF `--s1`, MID `--s0`, FWD `--s5`) + name plate +
xP (captain doubled). **Captain** = pulsing accent "C" armband (`@keyframes
pulseRing`); **vice** = "V"; unavailable = status dot. Bench is a separate strip
below (dimmed avatars). Players **pop in staggered** (`@keyframes popIn`, delay by
index). Hover lifts the avatar and shows a mini stat card (team, price, xP next, xP6,
form, owned). Click selects (accent ring) → opens Player detail.

**PlayerAvatar:** the current app uses real FPL mugshots
(`resources.premierleague.com/.../p{code}.png`). **Keep that** — render the photo
when `code` is present, and fall back to the kit-avatar (team color + initials)
shown in the prototype when the photo is missing/errors. The kit avatar is the
designed fallback, not a replacement.

**Captain card:** big chosen captain (avatar + "C" + fixture + **captain xP**
count-up = pred×2), then a list of candidates. Each candidate row: avatar · name ·
fixture + **FDR pill** · a **floor→ceiling bar** with an expected-value tick · xP.
**Clicking a candidate sets the captain** → the pitch armband moves and the header
"Live XI projection" + captain xP **re-count live**. (This is the signature
interaction — preserve it.)

**Transfer card:** OUT→IN with avatars (red OUT / accent IN tags), a swap glyph with
"free"/"−4" hit, two meters (GW uplift xP count-up; Confidence % with bar), a
rationale sentence, and actions: **Apply transfer** (toggles — swaps the OUT player
for IN on the pitch and updates value/bank) + **Alternatives** (expands a list of
other swaps with their uplift). Clicking either player opens their detail.

**Chip card:** 2×2 of chips (Wildcard, Bench Boost, Triple Captain, Free Hit) each
showing best GW + EV (used chips dimmed with a "used" tag); selecting one shows its
rationale note below.

**Player detail drawer:** avatar + name + team/pos (+ status tag) + price + ownership;
a 4-up stat grid (xP next [accent] · xP6 · form · pred mins); a "Last 8 GW returns"
**bar chart**; a "Next 5 fixtures" row of FDR-colored opponent pills.

### 2) Model Performance — `pages/ModelPerformance.tsx`
**Purpose:** compare strategies and inspect model quality without cramming — focused
tabs, comparison-first.

**Header:** H1 "Model performance" + subtitle, and a right-aligned **segmented tab
bar**: Compare · Predicted vs actual · Optimal XI · Weight adaptation · Player search.

- **Compare** (default): a row of **strategy chips** (colored by series, toggle to
  include/exclude). Two-column grid:
  - **Left — chart card** with a segmented **Cumulative / Weekly / Totals**.
    Cumulative & Weekly = multi-series line over GW with a **dual-handle GW-range
    slider**; Totals = grouped bars (Total vs Net-after-hits). Hovering the
    **Leaderboard** dims the other lines and emphasizes that strategy.
  - **Right — Leaderboard card**: strategies ranked by total, each row = rank ·
    color dot · name · (net, hits) · **total (count-up)** · delta vs leader
    (−N in red, "leader" in accent). Hover row ↔ chart emphasis is bidirectional.
- **Predicted vs actual:** 4 KPI tiles (Rank IC [accent] · RMSE · MAE · Bias, count-
  ups) → per-GW **dual-axis line** (IC left 0–0.6, RMSE/MAE right) → two-column:
  **Calibration** grouped bars (predicted vs actual by xP bucket) + **By position**
  list (IC bar + RMSE/bias + IC value per GK/DEF/MID/FWD).
- **Optimal XI:** 3 KPI tiles (Σ predicted xP · Σ actual pts · Realised %) + grouped
  bars predicted-XI-xP vs actual per GW.
- **Weight adaptation:** intro copy + a multi-series line of online-Hedge member
  weights over the season (one line per member, series palette).
- **Player search:** two columns — search card (text input + position segmented
  filter; results = avatar · name (+status dot) · team badge/pos/price · **sparkline**
  · xP) and the **Player detail** drawer (reuse the Planner one).

### 3) Settings — `pages/Settings.tsx`
**Purpose:** manage entry/season, model/strategy, optimiser params, notifications,
secrets — calm and grouped.

**Layout:** single column, `max-width:880px`. Section cards each with an icon + title:
- **Entry & season:** entry id (mono), season (mono), planning horizon (slider 1–10).
- **Model & strategy:** active model select, optimiser strategy select.
- **Optimisation:** sliders — free-transfer value (0–3, .1), future-GW decay
  (0.6–1, .01), EO weight (0–1, .05), EV threshold (0–6, .5).
- **Notifications:** email/push toggles; if email on, From/To inputs reveal.
- **Secrets:** write-only password inputs (API-Football key, SMTP password) with a
  "stored / not set" state and a **Set** button.

A **save bar** slides up from the bottom (centered pill) **only when the form is
dirty**: "You have unsaved changes" + Reset + Save changes.

---

## Interactions & Behavior
- **Count-ups:** every headline number animates 0→value, easeOutCubic, ~900ms,
  gated by `--motion`. **Must land on the final value even if rAF is throttled**
  (background tab) — the prototype adds a `setTimeout(dur+400ms)` fallback that sets
  the final value. Keep this guarantee. (In React, a small `useCountUp(value)` hook.)
- **Charts draw in:** line paths animate via `stroke-dashoffset` (`@keyframes
  dashIn`), bars grow height via CSS transition, sparklines dash-in. Stagger lines
  by series index.
- **Robustness "settle" net (important):** entrance animations must never leave
  content invisible if the animation clock is paused. The prototype adds an
  `.anim-settled` class to `<html>` ~1.3s after each page mount that forces
  `opacity:1; transform:none; stroke-dashoffset:0`. In React, prefer the cleaner
  equivalent: drive reveals with IntersectionObserver/`useEffect` state (not raw
  `requestAnimationFrame` toggles), and have the resting state be fully visible so a
  paused clock can't hide anything. Bars/mini-bars set their final size in a
  `useEffect`, not in rAF.
- **Hover:** cards lift (`translateY(-3px)` + stronger border/shadow); chart hover
  shows a crosshair + per-series dots + a themed tooltip; table rows tint
  `--surface-2`; pitch players lift + mini card.
- **Segmented controls:** a sliding "pill" animates under the active option
  (measure the active button's offset/width, animate `left/width`).
- **Theme toggle:** sets `data-theme="dark"|"light"` on `<html>`; persist.
- **Ticker:** infinite scroll, pause on hover.
- **Deadline countdown:** `setInterval` 1s.
- **Transitions:** default 180ms, cubic-bezier(.2,.7,.3,1); all multiplied by
  `--motion`.

## State Management
Use the repo's **TanStack Query** for all server data (it's already set up in the
pages). Local UI state needed:
- Planner: `view` (team|model), `captainId`, `transferApplied` (bool), `selectedPlayer`.
  Live projection + formation + value/bank are **derived** from these.
- Performance: `tab`, `pickedStrategies[]`, `compareMetric` (cumulative|weekly|totals),
  `focusedStrategy`, `gwRange [lo,hi]`, plus `posFilter`, `query`, `selectedPlayer`
  for search.
- Settings: a local draft of `GeneralSettings` + `dirty` flag; save via
  `api.saveSettings` / `api.saveSecrets`.
- App: `theme`, `accentHue`, `density`, `motion` (persist to localStorage; `theme`
  also exists in `GeneralSettings.theme`). Active route via React Router.

---

## Data Mapping (prototype mock → real `lib/api.ts`)
**Replace `data.js` entirely.** The prototype's `window.FPL` shape was built to mirror
the API. Mapping:

| Prototype | Real source (`api.*` → type in `lib/api.ts`) | Notes |
|---|---|---|
| `byId[].x1 / x6 / mins / price / status` | `predictions()` → `PlayerPrediction.xp_next1 / xp_next6 / pred_minutes / price / status` | core |
| `byId[].form / own / last` | — | **not in API** — compute from `playerHistory()` (recent mean / last GW) or add backend fields; until then derive client-side |
| `SQUAD` (your team) | `trackedEntry(id)` → `TrackedDetail` (entry, picks w/ `slot`,`multiplier`,`captain`,`vice`) | starters = slot ≤ 11 |
| header KPIs (total/rank/value/bank) | `TrackedEntry.total_points / overall_rank / team_value / bank` | |
| Model XI toggle | `squad(season,gw,version)` → `Squad` (picks w/ `start`,`captain`,`xp`,`formation`) | |
| `CAPTAIN.candidates` | derive from `predictions()` top xP among your starters (xp, ceiling/floor, fixture, FDR, EO) | ceiling/floor/EO may need backend; else estimate |
| `TRANSFER` | `planner(entry,season,gw,{horizon})` → `PlannerResult.rationale` (`transfers_in/out`, `captain`, `gw0_hit`, `plan_net_xp`, `hold_net_xp`, `uplift`) + `ev_uplift`, `confidence`, `bank` | "Alternatives" = top-N planner options if exposed |
| `CHIPS` | from planner/recommendations (`api.recommendations`) | chip EV/timing may need backend support |
| `STRATEGIES` (compare) | `compareModels(season, strategy[], version)` → `CompareRun[]` (`total_points`,`net_points`,`total_hits`,`per_gw[{gw,points}]`) | cumulative = running sum of `per_gw.points` |
| `ACC_*` | `accuracy(season,version)` → `Accuracy` (`per_gw`,`per_position`,`calibration`,`overall`) | direct |
| `OPTXI` | `optimalXi(season,version)` → `OptimalXi` (`gws[{gw,predicted_xi_xp,actual_points,...}]`,`totals`) | direct |
| `HEDGE` | `hedgeWeights(season)` → `HedgeWeights` (`members`,`series[{gw,weights}]`) | direct |
| Player search | `searchPlayers(q,season)` → `PlayerSearchResult`; detail uses `playerHistory(id,season)` | |
| Settings | `settings()` → `SettingsPayload`; `saveSettings`, `saveSecrets`, `models()` | |
| Ticker | derive (status/news from predictions, fixtures) or a small endpoint | optional |
| FDR / team colors | team kit colors are in `data.js` `TEAMS{}`; **keep this map** as a static `teams.ts` (codes, names, kit/trim/ink) — handy for badges/avatars even though it's not in the API |

Team kit colors and the FDR color scale (in `theme.css`/`components.jsx`) are
**design data** — copy them into a small static module; they don't come from the API.

---

## Assets
- **Fonts:** Archivo + JetBrains Mono (Google Fonts).
- **Player photos:** official FPL mugshots
  `https://resources.premierleague.com/premierleague/photos/players/110x140/p{code}.png`
  (already used by the repo's `PlayerAvatar`). Kit-avatar fallback is CSS-drawn
  (no asset).
- **Icons:** lucide-react (already a dependency).
- **Team kit colors:** static map in the design files (`TEAMS` in `data.js`).
- No bitmap/illustration assets — everything else is CSS/SVG.

---

## Screenshots
Annotated reference images of each screen/state are in `screenshots/` (caption
banner names the screen + key callouts):
- `01_team_planner.png` — Planner overview (dark)
- `02_planner_insights.png` — Captain + Transfer insight rail
- `03_performance_compare.png` — Compare (chips, chart, leaderboard)
- `04_performance_accuracy.png` — Predicted vs actual
- `05_player_search.png` — Player search + detail drawer
- `06_settings.png` — Settings
- `07_light_theme.png` — Light theme

(Captured at ~917px wide, so two-column page grids appear stacked — at ≥1080px they
sit side-by-side as described in each screen's **Layout**.)

## Files
In `design_reference/`:
- `LazyFPL Dashboard.html` — open this in a browser to see the finished design (all
  pages, both themes, Tweaks). Entry point that loads the scripts below.
- `app/theme.css` — **all design tokens, layout, component classes, keyframes**
  (the most important file to translate into `index.css` + `tailwind.config.js`).
- `app/components.jsx` — primitives: `CountUp`, `Card`, `Segmented`, `Chip`,
  `KitAvatar`, `TeamBadge`, `FDRpill`, `StatTile`, `MiniBar`, `StatusDot`, `Icon`,
  hooks (`useInView`, `useMotion`).
- `app/charts.jsx` — `LineChart`, `BarChart`, `Sparkline` (animated SVG; the
  draw-in + hover-tooltip logic to replicate or restyle in Recharts).
- `app/pitch.jsx` — the pitch, kit avatars, captain armband, hover cards.
- `app/planner.jsx` / `app/performance.jsx` / `app/settings.jsx` — the three pages,
  incl. all interactions described above.
- `app/main.jsx` — shell (sidebar, topbar, ticker, countdown, routing, Tweaks wiring).
- `app/data.js` — **mock data only; do not port.** Use it as a spec for the shapes,
  then delete in favor of `lib/api.ts`.
- `app/tweaks-panel.jsx` — the Tweaks panel runtime (optional; can be a dev-only
  control or folded into Settings as "Appearance").

### Suggested implementation order
1. Tokens → `index.css` + `tailwind.config.js` (dark+light, accent oklch, series,
   density/motion vars, fonts). Verify the existing app reskins instantly.
2. Shared primitives in `components/ui.tsx` (Card, Segmented, Chip, StatTile,
   CountUp hook, StatusDot, FDR pill, MiniBar).
3. Charts (port SVG or restyle Recharts) + count-ups.
4. Pitch + PlayerAvatar (photo with kit-avatar fallback) + armband/hover.
5. Layout shell (sidebar/topbar/ticker/countdown/theme toggle) in `Layout.tsx`.
6. Pages, wired to `lib/api.ts` via TanStack Query, in the order TeamPlanner →
   ModelPerformance → Settings.
7. Tweaks (accent/density/motion) + persistence; honor `prefers-reduced-motion`.
8. Responsive passes at 1080 / 880 / 560px.

### Acceptance checklist
- [ ] Dark + light both correct; theme persists.
- [ ] All headline numbers count up and **always end on the real value** (no zeros).
- [ ] Charts draw in and show hover crosshair tooltips; nothing stays invisible if a
      tab is backgrounded.
- [ ] Planner: changing captain re-projects live; Apply transfer swaps on the pitch.
- [ ] Performance Compare: chip toggles, metric switch, GW-range slider, and
      leaderboard↔chart emphasis all work.
- [ ] Player photos load with graceful kit-avatar fallback.
- [ ] No `backdrop-filter` on persistent chrome.
- [ ] Responsive at 1080/880/560.
```
