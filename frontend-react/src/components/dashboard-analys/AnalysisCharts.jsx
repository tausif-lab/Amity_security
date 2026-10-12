// Small dependency-free SVG charts. They scale to the width of their container.
const W = 600, H = 220;
const PAD = { l: 38, r: 12, t: 12, b: 28 };
const innerW = W - PAD.l - PAD.r;
const innerH = H - PAD.t - PAD.b;

const shortDate = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

function Grid({ max, unit = "", y }) {
  return [0, 0.5, 1].map((t) => (
    <g key={t}>
      <line x1={PAD.l} x2={W - PAD.r} y1={y(max * t)} y2={y(max * t)} stroke="#1f2937" />
      <text x={PAD.l - 6} y={y(max * t) + 3} textAnchor="end" fontSize="9" fill="#6b7280">
        {Math.round(max * t)}{unit}
      </text>
    </g>
  ));
}

function XLabels({ labels, xAt }) {
  const every = Math.ceil(labels.length / 6) || 1;
  return labels.map((l, i) =>
    i % every === 0 || i === labels.length - 1 ? (
      <text key={i} x={xAt(i)} y={H - 8} textAnchor="middle" fontSize="9" fill="#6b7280">{l}</text>
    ) : null);
}

// points: [{ label, value }]
export function LineChart({ points, max = 100, unit = "%", title }) {
  const n = points.length;
  const y = (v) => PAD.t + innerH - (Math.min(Math.max(v, 0), max) / max) * innerH;
  const xAt = (i) => (n <= 1 ? PAD.l + innerW / 2 : PAD.l + (i * innerW) / (n - 1));
  const coords = points.map((p, i) => [xAt(i), y(p.value)]);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={title}>
      <Grid max={max} unit={unit} y={y} />
      {n > 1 && <polyline fill="none" stroke="#ffffff" strokeWidth="1.5"
        points={coords.map((c) => c.join(",")).join(" ")} />}
      {coords.map(([cx, cy], i) => (
        <circle key={i} cx={cx} cy={cy} r="3" fill="#ffffff">
          <title>{points[i].label}: {points[i].value}{unit}</title>
        </circle>
      ))}
      <XLabels labels={points.map((p) => p.short)} xAt={xAt} />
    </svg>
  );
}

// data: [{ label, short, values: { key: number } }]   series: [{ key, label, color }]
export function StackedBarChart({ data, series, title }) {
  const totals = data.map((d) => series.reduce((s, k) => s + (d.values[k.key] ?? 0), 0));
  const max = Math.max(1, ...totals);
  const y = (v) => PAD.t + innerH - (v / max) * innerH;
  const band = innerW / Math.max(data.length, 1);
  const barW = Math.min(band * 0.6, 36);
  const xAt = (i) => PAD.l + band * i + band / 2;
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={title}>
        <Grid max={max} y={y} />
        {data.map((d, i) => {
          let base = 0;
          return (
            <g key={i}>
              {series.map((k) => {
                const v = d.values[k.key] ?? 0;
                const rect = v > 0 && (
                  <rect key={k.key} x={xAt(i) - barW / 2} width={barW} y={y(base + v)}
                    height={y(base) - y(base + v)} fill={k.color}>
                    <title>{d.label}: {v} {k.label}</title>
                  </rect>
                );
                base += v;
                return rect;
              })}
            </g>
          );
        })}
        <XLabels labels={data.map((d) => d.short)} xAt={xAt} />
      </svg>
      <div className="flex flex-wrap gap-4 mt-2 text-[10px] text-gray-400">
        {series.map((k) => (
          <span key={k.key} className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5" style={{ background: k.color }} /> {k.label}
          </span>
        ))}
      </div>
    </>
  );
}

// rows: [{ name, label, failed, total }]  : bar = share of audits where the rule failed
export function RuleFailureList({ rows }) {
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.name}>
          <div className="flex justify-between gap-3 text-xs mb-1">
            <span className="text-gray-200 break-words min-w-0">{r.label}</span>
            <span className="text-gray-500 shrink-0">failed {r.failed} of {r.total}</span>
          </div>
          <div className="h-1.5 bg-gray-900">
            <div className="h-full bg-red-500" style={{ width: `${r.total ? (100 * r.failed) / r.total : 0}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export { shortDate };