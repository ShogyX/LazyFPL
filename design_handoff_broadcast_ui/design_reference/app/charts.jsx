/* Hand-built animated SVG charts for LazyFPL. Exports to window.
   Draw-in animation + interactive hover crosshair/tooltip. Themed via CSS vars. */
const SERIES = ["var(--s0)", "var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"];

function useMeasure() {
  const ref = React.useRef(null);
  const [w, setW] = React.useState(0);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((es) => setW(es[0].contentRect.width));
    ro.observe(ref.current);
    setW(ref.current.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function niceTicks(min, max, n = 4) {
  if (min === max) { min -= 1; max += 1; }
  const span = max - min, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag, step = (norm >= 5 ? 5 : norm >= 2 ? 2 : norm >= 1 ? 1 : 0.5) * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const out = []; for (let v = lo; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

/* ---------------- LineChart ---------------- */
function LineChart({ data, xKey, series, height = 280, area, yDomain, rightDomain, yFormat = (v) => v, rightFormat = (v) => v, xFormat = (v) => v, legend = true, animateKey }) {
  const [wrapRef, W] = useMeasure();
  const [hi, setHi] = React.useState(null);
  const motion = useMotion();
  const padL = 38, padR = series.some((s) => s.axis === "right") ? 38 : 12, padT = 12, padB = 26;
  const H = height;
  const iw = Math.max(10, W - padL - padR), ih = H - padT - padB;

  const leftKeys = series.filter((s) => s.axis !== "right");
  const rightKeys = series.filter((s) => s.axis === "right");
  const extent = (keys, dom) => {
    if (dom && dom !== "auto") return dom;
    let mn = Infinity, mx = -Infinity;
    data.forEach((d) => keys.forEach((s) => { const v = d[s.key]; if (v != null) { mn = Math.min(mn, v); mx = Math.max(mx, v); } }));
    if (!isFinite(mn)) { mn = 0; mx = 1; }
    const pad = (mx - mn) * 0.12 || 1; return [Math.min(mn, dom && dom[0] === 0 ? 0 : mn - pad * 0.3), mx + pad];
  };
  const [lMin, lMax] = extent(leftKeys, yDomain);
  const [rMin, rMax] = rightKeys.length ? extent(rightKeys, rightDomain) : [0, 1];
  const xN = data.length;
  const X = (i) => padL + (xN <= 1 ? iw / 2 : (i / (xN - 1)) * iw);
  const YL = (v) => padT + ih - ((v - lMin) / (lMax - lMin || 1)) * ih;
  const YR = (v) => padT + ih - ((v - rMin) / (rMax - rMin || 1)) * ih;

  const ticks = niceTicks(lMin, lMax, 4);
  const path = (s) => {
    const Y = s.axis === "right" ? YR : YL;
    return data.map((d, i) => (d[s.key] == null ? null : `${i === 0 || data[i - 1][s.key] == null ? "M" : "L"}${X(i).toFixed(1)} ${Y(d[s.key]).toFixed(1)}`)).filter(Boolean).join(" ");
  };

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const i = Math.max(0, Math.min(xN - 1, Math.round(((x - padL) / iw) * (xN - 1))));
    setHi(i);
  };
  const xLabelEvery = Math.ceil(xN / Math.max(4, Math.floor(iw / 52)));
  const showXLabel = (i) => i === xN - 1 || (i % xLabelEvery === 0 && (xN - 1 - i) >= xLabelEvery * 0.6);

  return (
    <div ref={wrapRef} style={{ position: "relative", width: "100%" }}>
      {W > 0 && (
        <svg width={W} height={H} style={{ display: "block", overflow: "visible" }}>
          {/* grid + y labels */}
          {ticks.map((t, k) => (
            <g key={k}>
              <line x1={padL} x2={padL + iw} y1={YL(t)} y2={YL(t)} stroke="var(--line)" strokeWidth="1" />
              <text x={padL - 7} y={YL(t) + 3.5} textAnchor="end" fontSize="10.5" fontFamily="JetBrains Mono" fill="var(--fg-faint)">{yFormat(t)}</text>
            </g>
          ))}
          {/* right axis labels */}
          {rightKeys.length > 0 && niceTicks(rMin, rMax, 4).map((t, k) => (
            <text key={k} x={padL + iw + 7} y={YR(t) + 3.5} textAnchor="start" fontSize="10.5" fontFamily="JetBrains Mono" fill="var(--fg-faint)">{rightFormat(t)}</text>
          ))}
          {/* x labels */}
          {data.map((d, i) => showXLabel(i) && (
            <text key={i} x={X(i)} y={H - 7} textAnchor="middle" fontSize="10.5" fontFamily="JetBrains Mono" fill="var(--fg-faint)">{xFormat(d[xKey])}</text>
          ))}
          {/* area fill under first left series */}
          {area && leftKeys[0] && (
            <path d={`${path(leftKeys[0])} L${X(xN - 1)} ${padT + ih} L${X(0)} ${padT + ih} Z`}
              fill={leftKeys[0].color || SERIES[0]} opacity="0.10" style={{ animation: `fadeUp ${0.6 / motion}s ease both` }} />
          )}
          {/* crosshair */}
          {hi != null && <line x1={X(hi)} x2={X(hi)} y1={padT} y2={padT + ih} stroke="var(--line-2)" strokeWidth="1" strokeDasharray="3 3" />}
          {/* series paths */}
          {series.map((s, si) => {
            const d = path(s); const len = 1400;
            return <path key={s.key} d={d} fill="none" stroke={s.color || SERIES[si % 6]} strokeWidth={s.width || 2.4}
              strokeLinecap="round" strokeLinejoin="round" strokeDasharray={s.dashed ? "5 5" : len}
              strokeDashoffset={s.dashed ? 0 : len}
              style={s.dashed ? {} : { animation: `dashIn ${1.05 / motion}s cubic-bezier(.3,.8,.3,1) ${si * 0.08}s forwards` }} />;
          })}
          {/* hover dots */}
          {hi != null && series.map((s, si) => {
            const v = data[hi][s.key]; if (v == null) return null;
            const Y = s.axis === "right" ? YR : YL;
            return <circle key={s.key} cx={X(hi)} cy={Y(v)} r="4.5" fill="var(--surface)" stroke={s.color || SERIES[si % 6]} strokeWidth="2.5" />;
          })}
          {/* capture */}
          <rect x={padL} y={padT} width={iw} height={ih} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHi(null)} />
        </svg>
      )}
      {/* tooltip */}
      {hi != null && W > 0 && (
        <div style={{ position: "absolute", top: 4, left: Math.min(W - 150, Math.max(0, X(hi) + 10)),
          background: "var(--surface-3)", border: "1px solid var(--line-2)", borderRadius: 9, padding: "8px 10px",
          pointerEvents: "none", boxShadow: "var(--shadow)", minWidth: 110, zIndex: 5 }}>
          <div className="eyebrow" style={{ marginBottom: 5 }}>{xFormat(data[hi][xKey])}</div>
          {series.map((s, si) => data[hi][s.key] != null && (
            <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, marginTop: 2 }}>
              <span style={{ width: 9, height: 9, borderRadius: 3, background: s.color || SERIES[si % 6] }} />
              <span style={{ color: "var(--fg-dim)" }}>{s.label}</span>
              <span className="num" style={{ marginLeft: "auto", fontWeight: 700 }}>
                {(s.axis === "right" ? rightFormat : yFormat)(data[hi][s.key])}
              </span>
            </div>
          ))}
        </div>
      )}
      {legend && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", marginTop: 8, paddingLeft: padL }}>
          {series.map((s, si) => (
            <span key={s.key} style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12, color: "var(--fg-dim)" }}>
              <span style={{ width: 14, height: 3, borderRadius: 2, background: s.color || SERIES[si % 6], opacity: s.dashed ? 0.6 : 1 }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- BarChart (single or grouped) ---------------- */
function BarChart({ data, xKey, series, height = 280, yFormat = (v) => v, xFormat = (v) => v, legend = true, horizontalLabels }) {
  const [wrapRef, W] = useMeasure();
  const [hi, setHi] = React.useState(null);
  const [grown, setGrown] = React.useState(false);
  const motion = useMotion();
  React.useEffect(() => { const id = setTimeout(() => setGrown(true), 30); return () => clearTimeout(id); }, []);
  const padL = 38, padR = 10, padT = 12, padB = horizontalLabels ? 40 : 26;
  const H = height, iw = Math.max(10, W - padL - padR), ih = H - padT - padB;
  let mx = 0; data.forEach((d) => series.forEach((s) => { mx = Math.max(mx, d[s.key] || 0); }));
  const ticks = niceTicks(0, mx, 4); mx = ticks[ticks.length - 1];
  const Y = (v) => padT + ih - (v / (mx || 1)) * ih;
  const groupW = iw / data.length, barGap = 0.22 * groupW, innerW = groupW - barGap;
  const bw = innerW / series.length;
  const barLblEvery = horizontalLabels ? 1 : Math.max(1, Math.ceil(data.length / Math.max(6, Math.floor(iw / 34))));

  return (
    <div ref={wrapRef} style={{ position: "relative", width: "100%" }}>
      {W > 0 && (
        <svg width={W} height={H} style={{ display: "block", overflow: "visible" }}>
          {ticks.map((t, k) => (
            <g key={k}>
              <line x1={padL} x2={padL + iw} y1={Y(t)} y2={Y(t)} stroke="var(--line)" />
              <text x={padL - 7} y={Y(t) + 3.5} textAnchor="end" fontSize="10.5" fontFamily="JetBrains Mono" fill="var(--fg-faint)">{yFormat(t)}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const gx = padL + i * groupW + barGap / 2;
            const active = hi === i;
            return (
              <g key={i} onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)}>
                <rect x={padL + i * groupW} y={padT} width={groupW} height={ih} fill={active ? "var(--surface-2)" : "transparent"} rx="4" />
                {series.map((s, si) => {
                  const v = d[s.key] || 0; const h = grown ? (v / mx) * ih : 0;
                  return <rect key={s.key} x={gx + si * bw + bw * 0.12} width={bw * 0.76} y={padT + ih - h} height={h}
                    rx={Math.min(4, bw * 0.2)} fill={s.color || SERIES[si % 6]} opacity={active || hi == null ? 1 : 0.55}
                    style={{ transition: `height ${0.7 / motion}s cubic-bezier(.3,.8,.3,1) ${i * 0.012}s, y ${0.7 / motion}s cubic-bezier(.3,.8,.3,1) ${i * 0.012}s, opacity .15s` }} />;
                })}
                {horizontalLabels ? (
                  <text x={gx + innerW / 2} y={H - padB + 14} textAnchor="end" transform={`rotate(-32 ${gx + innerW / 2} ${H - padB + 14})`} fontSize="10.5" fill="var(--fg-faint)">{xFormat(d[xKey])}</text>
                ) : (i % barLblEvery === 0 &&
                  <text x={gx + innerW / 2} y={H - 7} textAnchor="middle" fontSize="10.5" fontFamily="JetBrains Mono" fill="var(--fg-faint)">{xFormat(d[xKey])}</text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      {hi != null && W > 0 && (
        <div style={{ position: "absolute", top: 4, left: Math.min(W - 150, Math.max(0, padL + hi * groupW + groupW)), background: "var(--surface-3)", border: "1px solid var(--line-2)", borderRadius: 9, padding: "8px 10px", pointerEvents: "none", boxShadow: "var(--shadow)", zIndex: 5 }}>
          <div className="eyebrow" style={{ marginBottom: 5 }}>{xFormat(data[hi][xKey])}</div>
          {series.map((s, si) => (
            <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, marginTop: 2 }}>
              <span style={{ width: 9, height: 9, borderRadius: 3, background: s.color || SERIES[si % 6] }} />
              <span style={{ color: "var(--fg-dim)" }}>{s.label}</span>
              <span className="num" style={{ marginLeft: "auto", fontWeight: 700 }}>{yFormat(data[hi][s.key] || 0)}</span>
            </div>
          ))}
        </div>
      )}
      {legend && series.length > 1 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", marginTop: 8, paddingLeft: padL }}>
          {series.map((s, si) => (
            <span key={s.key} style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12, color: "var(--fg-dim)" }}>
              <span style={{ width: 11, height: 11, borderRadius: 3, background: s.color || SERIES[si % 6] }} />{s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- Sparkline ---------------- */
function Sparkline({ data, width = 110, height = 30, color = "var(--accent)", fill = true }) {
  const motion = useMotion();
  if (!data || !data.length) return null;
  const mn = Math.min(...data), mx = Math.max(...data);
  const X = (i) => (i / (data.length - 1)) * width;
  const Y = (v) => height - 3 - ((v - mn) / (mx - mn || 1)) * (height - 6);
  const d = data.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block", overflow: "visible" }}>
      {fill && <path d={`${d} L${width} ${height} L0 ${height} Z`} fill={color} opacity="0.12" />}
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        strokeDasharray="600" strokeDashoffset="600" style={{ animation: `dashIn ${0.9 / motion}s ease forwards` }} />
      <circle cx={X(data.length - 1)} cy={Y(data[data.length - 1])} r="2.6" fill={color} />
    </svg>
  );
}

Object.assign(window, { LineChart, BarChart, Sparkline, SERIES, niceTicks });
