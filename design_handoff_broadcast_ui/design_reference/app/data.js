/* LazyFPL — mock dataset (2025-26 season, ~GW34). Real PL teams & players for
   believability. Numbers are plausible model outputs, generated to feel alive.
   Attached to window.FPL. Avatars are team-kit + initials (never 404). */
(function () {
  // ---- 20 PL teams (2025-26): code, name, short, primary kit, accent, text ----
  const TEAMS = {
    ARS: { name: "Arsenal",            short: "ARS", kit: "#EF0107", trim: "#FFFFFF", ink: "#fff" },
    AVL: { name: "Aston Villa",        short: "AVL", kit: "#95BFE5", trim: "#670E36", ink: "#3a0a20" },
    BOU: { name: "Bournemouth",        short: "BOU", kit: "#DA291C", trim: "#000000", ink: "#fff" },
    BRE: { name: "Brentford",          short: "BRE", kit: "#E30613", trim: "#FFFFFF", ink: "#fff" },
    BHA: { name: "Brighton",           short: "BHA", kit: "#0057B8", trim: "#FFCD00", ink: "#fff" },
    BUR: { name: "Burnley",            short: "BUR", kit: "#6C1D45", trim: "#99D6EA", ink: "#fff" },
    CHE: { name: "Chelsea",            short: "CHE", kit: "#034694", trim: "#FFFFFF", ink: "#fff" },
    CRY: { name: "Crystal Palace",     short: "CRY", kit: "#1B458F", trim: "#C4122E", ink: "#fff" },
    EVE: { name: "Everton",            short: "EVE", kit: "#003399", trim: "#FFFFFF", ink: "#fff" },
    FUL: { name: "Fulham",             short: "FUL", kit: "#FFFFFF", trim: "#000000", ink: "#111" },
    LEE: { name: "Leeds United",       short: "LEE", kit: "#FFFFFF", trim: "#1D428A", ink: "#1d428a" },
    LIV: { name: "Liverpool",          short: "LIV", kit: "#C8102E", trim: "#00B2A9", ink: "#fff" },
    MCI: { name: "Manchester City",    short: "MCI", kit: "#6CABDD", trim: "#1C2C5B", ink: "#0b1733" },
    MUN: { name: "Manchester United",  short: "MUN", kit: "#DA291C", trim: "#FBE122", ink: "#fff" },
    NEW: { name: "Newcastle",          short: "NEW", kit: "#241F20", trim: "#FFFFFF", ink: "#fff" },
    NFO: { name: "Nott'm Forest",      short: "NFO", kit: "#DD0000", trim: "#FFFFFF", ink: "#fff" },
    SUN: { name: "Sunderland",         short: "SUN", kit: "#EB172B", trim: "#211E1F", ink: "#fff" },
    TOT: { name: "Tottenham",          short: "TOT", kit: "#FFFFFF", trim: "#132257", ink: "#132257" },
    WHU: { name: "West Ham",           short: "WHU", kit: "#7A263A", trim: "#1BB1E7", ink: "#fff" },
    WOL: { name: "Wolves",             short: "WOL", kit: "#FDB913", trim: "#231F20", ink: "#2a2410" },
  };

  // difficulty grid: average upcoming-fixture difficulty per team (1 easy..5 hard)
  const FDR = {
    ARS: 2.4, AVL: 3.0, BOU: 2.8, BRE: 3.2, BHA: 3.1, BUR: 3.6, CHE: 2.7, CRY: 2.9,
    EVE: 3.3, FUL: 3.0, LEE: 3.8, LIV: 2.2, MCI: 2.5, MUN: 3.1, NEW: 2.6, NFO: 2.9,
    SUN: 3.7, TOT: 2.9, WHU: 3.4, WOL: 3.5,
  };

  // ---- players. p = price(£m), x1 = xP next GW, x6 = xP next 6, f = form (pts/gw),
  //      m = predicted minutes, own = % ownership, st = status, dpg = pts last GW ----
  // pos: 1 GK, 2 DEF, 3 MID, 4 FWD
  const P = (id, n, t, pos, p, x1, x6, f, m, own, st, dpg) =>
    ({ id, name: n, team: t, pos, price: p, x1, x6, form: f, mins: m, own, status: st || "a", last: dpg });

  const PLAYERS = [
    // GK
    P(1,  "Raya",        "ARS", 1, 5.7, 4.1, 24.0, 4.3, 90, 28.4, "a", 6),
    P(2,  "Sánchez",     "CHE", 1, 5.0, 3.8, 22.1, 3.9, 90, 14.2, "a", 2),
    P(3,  "Sels",        "NFO", 1, 5.3, 3.6, 21.0, 4.0, 90, 19.7, "a", 7),
    P(4,  "Pickford",    "EVE", 1, 5.5, 3.5, 20.4, 3.6, 90, 11.0, "a", 3),
    P(5,  "Petrović",    "BOU", 1, 4.6, 3.7, 21.6, 4.1, 90, 9.3, "a", 8),
    // DEF
    P(10, "Gabriel",     "ARS", 2, 6.3, 4.9, 27.8, 5.1, 90, 32.1, "a", 8),
    P(11, "Saliba",      "ARS", 2, 6.1, 4.3, 25.0, 4.2, 90, 18.4, "a", 2),
    P(12, "Van Dijk",    "LIV", 2, 6.4, 4.6, 26.4, 4.7, 90, 21.7, "a", 6),
    P(13, "Gvardiol",    "MCI", 2, 6.0, 4.4, 24.9, 4.5, 88, 17.9, "a", 5),
    P(14, "Muñoz",       "CRY", 2, 5.6, 4.7, 26.1, 5.4, 89, 24.8, "a", 9),
    P(15, "Hall",        "NEW", 2, 5.4, 4.5, 25.3, 4.8, 90, 22.3, "a", 6),
    P(16, "Senesi",      "BOU", 2, 4.9, 4.6, 25.8, 5.0, 90, 27.6, "a", 7),
    P(17, "Burn",        "NEW", 2, 4.7, 4.0, 22.0, 3.8, 90, 12.5, "a", 2),
    P(18, "Robinson",    "FUL", 2, 4.8, 3.9, 21.4, 3.7, 89, 10.1, "d", 1),
    P(19, "Andersen",    "FUL", 2, 4.5, 3.8, 20.8, 3.6, 90, 6.4, "a", 6),
    P(20, "Mykolenko",   "EVE", 2, 4.4, 3.6, 19.9, 3.4, 85, 4.8, "a", 2),
    // MID
    P(30, "Salah",       "LIV", 3, 14.6, 7.8, 43.2, 7.1, 90, 51.3, "a", 13),
    P(31, "Palmer",      "CHE", 3, 10.7, 6.4, 35.9, 5.9, 89, 33.8, "a", 9),
    P(32, "Saka",        "ARS", 3, 10.2, 6.7, 37.4, 6.3, 86, 29.4, "a", 11),
    P(33, "Mbeumo",      "MUN", 3, 8.3, 5.9, 33.1, 5.6, 90, 26.7, "a", 8),
    P(34, "Fernandes",   "MUN", 3, 9.0, 5.4, 30.6, 4.9, 90, 19.2, "a", 4),
    P(35, "Gordon",      "NEW", 3, 7.6, 5.6, 31.4, 5.2, 88, 17.5, "a", 9),
    P(36, "Rogers",      "AVL", 3, 7.1, 5.3, 29.8, 5.0, 87, 15.9, "a", 7),
    P(37, "Wirtz",       "LIV", 3, 8.8, 5.7, 32.0, 5.1, 84, 16.8, "a", 6),
    P(38, "Semenyo",     "BOU", 3, 7.3, 5.8, 32.6, 5.7, 90, 23.1, "a", 10),
    P(39, "Foden",       "MCI", 3, 8.0, 5.2, 29.1, 4.6, 82, 12.3, "a", 5),
    P(40, "Gakpo",       "LIV", 3, 7.7, 5.0, 28.3, 4.7, 80, 11.6, "a", 8),
    P(41, "Eze",         "ARS", 3, 7.4, 5.1, 28.9, 4.8, 83, 13.7, "d", 3),
    P(42, "Kluivert",    "BOU", 3, 6.6, 4.8, 27.0, 4.5, 84, 9.9, "a", 7),
    P(43, "Mitoma",      "BHA", 3, 6.5, 4.6, 25.7, 4.3, 85, 8.2, "a", 4),
    // FWD
    P(50, "Haaland",     "MCI", 4, 14.3, 8.1, 45.1, 7.4, 90, 56.8, "a", 15),
    P(51, "Isak",        "LIV", 4, 10.6, 6.6, 36.8, 6.0, 88, 24.9, "a", 9),
    P(52, "Watkins",     "AVL", 4, 8.8, 5.9, 33.0, 5.4, 89, 20.2, "a", 7),
    P(53, "Wood",        "NFO", 4, 7.4, 5.2, 28.7, 4.9, 90, 18.6, "a", 5),
    P(54, "Mateta",      "CRY", 4, 7.7, 5.6, 31.2, 5.3, 88, 21.4, "a", 9),
    P(55, "Cunha",       "MUN", 4, 7.2, 5.0, 27.9, 4.6, 86, 12.8, "a", 3),
    P(56, "Solanke",     "TOT", 4, 7.5, 4.9, 27.3, 4.4, 84, 10.7, "d", 2),
    P(57, "Welbeck",     "BHA", 4, 6.3, 4.7, 26.1, 4.5, 82, 9.1, "a", 8),
    P(58, "Thiago",      "BRE", 4, 6.1, 4.5, 25.0, 4.2, 85, 7.6, "a", 6),
    P(59, "Jackson",     "CHE", 4, 6.8, 4.4, 24.4, 4.0, 78, 6.9, "a", 2),
  ];
  const byId = Object.fromEntries(PLAYERS.map((p) => [p.id, p]));

  // ---- user's tracked team (GW34), formation 3-4-3 ----
  const SQUAD = {
    entry: 4318211, name: "xG Whisperers", gw: 34,
    totalPoints: 1987, rank: 184203, rankPct: 2.1, gwPoints: 71, bank: 1.4, value: 102.3,
    freeTransfers: 1,
    // slot order: GK, DEF..., MID..., FWD..., then bench (12-15)
    starters: [
      { id: 1,  cap: false, vice: false },         // Raya
      { id: 10, cap: false, vice: false },         // Gabriel
      { id: 14, cap: false, vice: false },         // Muñoz
      { id: 16, cap: false, vice: false },         // Senesi
      { id: 30, cap: true,  vice: false },         // Salah (C)
      { id: 31, cap: false, vice: false },         // Palmer
      { id: 32, cap: false, vice: true  },         // Saka (V)
      { id: 38, cap: false, vice: false },         // Semenyo
      { id: 50, cap: false, vice: false },         // Haaland
      { id: 54, cap: false, vice: false },         // Mateta
      { id: 53, cap: false, vice: false },         // Wood
    ],
    bench: [
      { id: 3,  cap: false, vice: false },         // Sels
      { id: 15, cap: false, vice: false },         // Hall
      { id: 36, cap: false, vice: false },         // Rogers
      { id: 57, cap: false, vice: false },         // Welbeck
    ],
  };

  // projected XI xP and captain doubling
  SQUAD.xiXp = +SQUAD.starters.reduce((s, p) => s + byId[p.id].x1 * (p.cap ? 2 : 1), 0).toFixed(1);

  // ---- this-week decision objects ----
  const CAPTAIN = {
    pick: 30, // Salah
    candidates: [
      { id: 30, xp: 7.8, ceiling: 17, floor: 2, fix: "BUR (H)", fdr: 2, eo: 38 },
      { id: 50, xp: 8.1, ceiling: 19, floor: 2, fix: "WOL (H)", fdr: 2, eo: 44 },
      { id: 32, xp: 6.7, ceiling: 15, floor: 1, fix: "NEW (A)", fdr: 3, eo: 21 },
      { id: 38, xp: 5.8, ceiling: 13, floor: 1, fix: "EVE (H)", fdr: 3, eo: 14 },
    ],
  };

  const TRANSFER = {
    out: 53, in: 51, // Wood -> Isak
    hit: 0, ft: 1,
    upliftGw: 1.4, upliftHorizon: 4.8, confidence: 0.72,
    bankAfter: 0.2, horizon: 6,
    reason: "Isak's 6-GW schedule swings green (LIV avg FDR 2.2) and his minutes are locked; Wood's underlying numbers are cooling and Forest's run hardens.",
    alternatives: [
      { out: 53, in: 52, uplift: 3.9, label: "Wood → Watkins" },
      { out: 54, in: 51, uplift: 3.1, label: "Mateta → Isak" },
      { out: 16, in: 14, uplift: 1.7, label: "Senesi → Muñoz (already owned)" },
    ],
  };

  const CHIPS = [
    { key: "wildcard", name: "Wildcard", best: "GW36", ev: 18.2, status: "available", note: "Schedule swing + price churn make a full reset worth ~18 pts over the run-in." },
    { key: "bboost",   name: "Bench Boost", best: "GW37", ev: 11.4, status: "available", note: "DGW37: four bench starters projected, all with two fixtures." },
    { key: "tripcap",  name: "Triple Captain", best: "GW37", ev: 9.7, status: "available", note: "Haaland double — ceiling north of 30 if City rotate kindly." },
    { key: "freehit",  name: "Free Hit", best: "GW33", ev: 0, status: "used", note: "Played in the blank — banked 24 over your hold." },
  ];

  // ---- live ticker: scores + price + news ----
  const TICKER = [
    { kind: "live", a: "LIV", b: "BUR", as: 2, bs: 0, min: "67'", note: "Salah 1G 1A" },
    { kind: "live", a: "MCI", b: "WOL", as: 3, bs: 1, min: "72'", note: "Haaland 2G" },
    { kind: "ft",   a: "ARS", b: "NEW", as: 1, bs: 1, min: "FT", note: "Saka 1A" },
    { kind: "price", dir: "up", name: "Semenyo", val: "£7.3", note: "+0.1" },
    { kind: "price", dir: "down", name: "Fernandes", val: "£9.0", note: "−0.1" },
    { kind: "news", name: "Eze", note: "knock — 75% chance GW35", flag: "d" },
    { kind: "live", a: "CRY", b: "EVE", as: 1, bs: 0, min: "58'", note: "Mateta 1G" },
    { kind: "price", dir: "up", name: "Muñoz", val: "£5.6", note: "+0.1" },
    { kind: "news", name: "Solanke", note: "doubtful — ankle", flag: "d" },
  ];

  // ---- model performance: backtest strategies, cumulative per GW ----
  // helper to build a believable cumulative curve
  function curve(perGwMean, jitterSeed, n) {
    let cum = 0, s = jitterSeed, out = [];
    for (let gw = 1; gw <= n; gw++) {
      s = (s * 9301 + 49297) % 233280;
      const r = s / 233280;
      const pts = Math.max(8, Math.round(perGwMean + (r - 0.5) * perGwMean * 0.9));
      cum += pts;
      out.push({ gw, points: pts, cum });
    }
    return out;
  }
  const NGW = 34;
  const STRATEGIES = [
    { key: "ensemble", name: "Ensemble (Hedge)", color: 0, total: 2042, net: 2018, hits: 6, per: curve(60.1, 11, NGW) },
    { key: "stacking", name: "Ridge Stack",      color: 1, total: 1994, net: 1962, hits: 8, per: curve(58.6, 23, NGW) },
    { key: "ict",      name: "ICT Heuristic",    color: 2, total: 1876, net: 1840, hits: 9, per: curve(55.2, 31, NGW) },
    { key: "perpos",   name: "Per-Position",     color: 3, total: 1951, net: 1923, hits: 7, per: curve(57.4, 41, NGW) },
    { key: "template", name: "Template EO",      color: 4, total: 1903, net: 1879, hits: 6, per: curve(56.0, 53, NGW) },
    { key: "naive",    name: "Naïve (last-GW)",  color: 5, total: 1721, net: 1689, hits: 8, per: curve(50.7, 67, NGW) },
  ];

  // accuracy: per-GW IC / RMSE / MAE for active model
  const ACC_GW = [];
  for (let gw = 1; gw <= NGW; gw++) {
    const s = (gw * 2654435761) % 1000 / 1000;
    ACC_GW.push({
      gw,
      ic: +(0.34 + Math.sin(gw / 3) * 0.07 + (s - 0.5) * 0.06).toFixed(3),
      rmse: +(2.55 - Math.cos(gw / 4) * 0.18 + (s - 0.5) * 0.12).toFixed(2),
      mae: +(1.78 - Math.cos(gw / 4) * 0.12 + (s - 0.5) * 0.08).toFixed(2),
    });
  }
  const ACC_POS = [
    { pos: "GK",  n: 612,  ic: 0.41, rmse: 1.92, bias: -0.04 },
    { pos: "DEF", n: 2244, ic: 0.33, rmse: 2.31, bias: 0.06 },
    { pos: "MID", n: 2380, ic: 0.38, rmse: 2.74, bias: -0.02 },
    { pos: "FWD", n: 884,  ic: 0.36, rmse: 2.98, bias: 0.09 },
  ];
  const CALIB = [
    { bucket: "0–1", pred: 0.7, actual: 0.9, n: 1820 },
    { bucket: "1–2", pred: 1.5, actual: 1.7, n: 1640 },
    { bucket: "2–3", pred: 2.5, actual: 2.4, n: 1120 },
    { bucket: "3–4", pred: 3.4, actual: 3.6, n: 720 },
    { bucket: "4–6", pred: 4.8, actual: 4.5, n: 540 },
    { bucket: "6+",  pred: 7.6, actual: 7.1, n: 280 },
  ];
  const ACC_OVERALL = { ic: 0.362, rmse: 2.57, mae: 1.74, bias: 0.02, n: 6120, gws: NGW };

  // optimal XI realised
  const OPTXI = [];
  for (let gw = 1; gw <= NGW; gw++) {
    const s = (gw * 40503) % 100 / 100;
    const pred = +(58 + Math.sin(gw / 2) * 5).toFixed(1);
    OPTXI.push({ gw, pred, actual: Math.round(pred * (0.82 + s * 0.4)) });
  }

  // online-hedge member weights over the season (stacked-ish)
  const MEMBERS = ["minutes", "goals-DC", "assists", "cleansheet", "bonus", "defcon"];
  const HEDGE = [];
  for (let gw = 1; gw <= NGW; gw++) {
    const base = MEMBERS.map((_, i) => 0.16 + Math.sin((gw + i * 5) / 6) * 0.07 + i * 0.005);
    const sum = base.reduce((a, b) => a + b, 0);
    const row = { gw };
    MEMBERS.forEach((m, i) => (row[m] = +(base[i] / sum).toFixed(3)));
    HEDGE.push(row);
  }

  window.FPL = {
    TEAMS, FDR, PLAYERS, byId, SQUAD, CAPTAIN, TRANSFER, CHIPS, TICKER,
    STRATEGIES, ACC_GW, ACC_POS, CALIB, ACC_OVERALL, OPTXI, MEMBERS, HEDGE,
    NGW, SEASON: "2025-26", GW: 34,
    POS: { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" },
  };
})();
