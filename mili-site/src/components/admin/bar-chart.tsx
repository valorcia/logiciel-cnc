import { fmtNum } from "./ui";

type Point = { day: string; value: number };

const dayLabel = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", timeZone: "UTC" });

/** "Nice" upper bound for the value axis. */
function niceMax(max: number): number {
  if (max <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(max));
  const unit = max / pow;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * pow;
}

/**
 * One measure per chart, one hue, one axis. Each bar carries a native tooltip
 * and the same figures are available as a table underneath.
 */
export function BarChart({ title, points, color = "#00D9FF" }: { title: string; points: Point[]; color?: string }) {
  const W = 640, H = 200, L = 40, R = 8, T = 12, B = 26;
  const max = niceMax(Math.max(0, ...points.map((p) => p.value)));
  const total = points.reduce((sum, p) => sum + p.value, 0);
  const slot = (W - L - R) / Math.max(points.length, 1);
  const barW = Math.max(2, Math.min(28, slot - 2));
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const labelEvery = Math.ceil(points.length / 6);

  return (
    <figure>
      <figcaption className="mb-3 flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-white">{title}</span>
        <span className="text-xs text-smoke">Total : <span className="tabular-nums text-ash">{fmtNum(total)}</span></span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${title} par jour, total ${total}`}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(max * f)} y2={y(max * f)} stroke="#23262e" strokeWidth="1" />
            <text x={L - 8} y={y(max * f) + 4} textAnchor="end" fontSize="11" fill="#71717a">{fmtNum(max * f)}</text>
          </g>
        ))}
        {points.map((p, i) => {
          const x = L + i * slot + (slot - barW) / 2;
          const h = Math.max(p.value > 0 ? 2 : 0, H - B - y(p.value));
          const r = Math.min(4, barW / 2, h);
          const date = dayLabel.format(new Date(`${p.day}T00:00:00Z`));
          return (
            <g key={p.day}>
              {/* Hit target taller than the mark, so the tooltip is easy to reach. */}
              <rect x={L + i * slot} y={T} width={slot} height={H - T - B} fill="transparent"><title>{`${date} : ${fmtNum(p.value)}`}</title></rect>
              {h > 0 && <path d={`M${x},${H - B} v${-(h - r)} q0,${-r} ${r},${-r} h${barW - 2 * r} q${r},0 ${r},${r} v${h - r} z`} fill={color} pointerEvents="none" />}
              {i % labelEvery === 0 && <text x={L + i * slot + slot / 2} y={H - 8} textAnchor="middle" fontSize="11" fill="#71717a">{date}</text>}
            </g>
          );
        })}
      </svg>
      <details className="mt-2 text-xs text-smoke">
        <summary>Voir les chiffres</summary>
        <table className="adm-table mt-2 max-w-xs">
          <thead><tr><th>Jour</th><th className="num">{title}</th></tr></thead>
          <tbody>{points.map((p) => <tr key={p.day}><td>{p.day}</td><td className="num">{fmtNum(p.value)}</td></tr>)}</tbody>
        </table>
      </details>
    </figure>
  );
}
