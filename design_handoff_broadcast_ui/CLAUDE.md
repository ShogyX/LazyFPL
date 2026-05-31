# CLAUDE.md — Kickoff: port the "Broadcast" UI into LazyFPL

You are implementing a UI redesign in the **existing LazyFPL frontend**
(`frontend/` — React 18 + Vite + TypeScript + Tailwind + Recharts + lucide-react +
React Router + TanStack Query). **Read `README.md` in this folder first — it is the
spec.**

## What this is
`design_reference/` holds a working **HTML/JS prototype** of the redesign and
`screenshots/` shows each screen/state. These are **references**, not code to ship.
Recreate the design in the real app's stack and patterns, and wire it to the live
read API via `frontend/src/lib/api.ts` (TanStack Query). **Do not** port the
prototype's `app/data.js` — it is mock data; the README's "Data Mapping" table tells
you which real `api.*` call + type feeds each piece.

## Rules
- High fidelity: match the tokens in README → "Design Tokens" exactly (dark + light,
  oklch accent, fixed series palette, density/motion vars, Archivo + JetBrains Mono).
- Keep the existing IA (Team Planner, Model Performance, Settings) and the FPL pitch.
- Keep player mugshots (`PlayerAvatar`), with the CSS kit-avatar as the fallback.
- Use `lucide-react` for icons (the prototype's inline `Icon` is only because it has
  no deps — mapping is in the README).
- Charts: either port the prototype's animated SVG charts or restyle Recharts with
  the tokens; either way add count-ups + hover-crosshair tooltips.
- **Do not put `backdrop-filter` on the sidebar/topbar** (it black-renders under
  capture/compositing — see README).
- Animations must never hide content if the tab is backgrounded: resting state is
  visible; reveals are progressive enhancements; count-ups must always land on the
  real value (README → "Interactions & Behavior").

## Suggested order (also in README)
1. Tokens → `index.css` + `tailwind.config.js`; confirm the app reskins instantly.
2. Shared primitives in `components/ui.tsx` (Card, Segmented, Chip, StatTile,
   useCountUp, StatusDot, FDR pill, MiniBar).
3. Charts (port SVG or restyle Recharts) + count-ups.
4. Pitch + PlayerAvatar (photo → kit-avatar fallback) + captain armband + hover.
5. Shell (sidebar / topbar / ticker / deadline countdown / theme toggle) in
   `Layout.tsx`.
6. Pages wired to `lib/api.ts`: TeamPlanner → ModelPerformance → Settings.
7. Tweaks (accent / density / motion) + persistence; honor `prefers-reduced-motion`.
8. Responsive passes at 1080 / 880 / 560px.

Finish against the README's acceptance checklist.
