import { useReducedMotion } from "framer-motion";
import { useTheme } from "@/lib/theme-context";

const LEGACY_NODES = [
  { label: "ERP", y: 46 },
  { label: "CRM", y: 96 },
  { label: "DB", y: 146 },
  { label: "AUTH", y: 196 },
];

const CLOUD_NODES = [
  { label: "COMPUTE", x: 800, y: 66 },
  { label: "DATA", x: 830, y: 121 },
  { label: "IDENTITY", x: 800, y: 176 },
];

// Each legacy node streams toward one cloud node; varied curvature and timing
// keep the corridor from reading as a mechanical, repeated loop.
const PATHS = [
  { from: 0, to: 0, dur: "3.4s", begin: "0s", hot: false },
  { from: 0, to: 1, dur: "4.1s", begin: "0.6s", hot: true },
  { from: 1, to: 0, dur: "3.8s", begin: "0.2s", hot: false },
  { from: 1, to: 1, dur: "3.2s", begin: "1.1s", hot: false },
  { from: 2, to: 1, dur: "4.4s", begin: "0.4s", hot: false },
  { from: 2, to: 2, dur: "3.6s", begin: "1.4s", hot: true },
  { from: 3, to: 2, dur: "3.9s", begin: "0.9s", hot: false },
];

function pathD(x1: number, y1: number, x2: number, y2: number) {
  const midX = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
}

/** Abstract schematic of a migration in progress - legacy systems on the left
 * streaming into a target cloud cluster on the right. Intentionally reads as
 * a technical topology diagram (an extension of the product's own digital
 * twin graph) rather than a literal illustration. */
// This diagram is drawn with literal SVG fill/stroke attributes rather than
// Tailwind classes, so it can't pick up a `dark:` variant automatically -
// picked explicitly per theme instead (mirrors GraphPage's riskHex approach).
const PALETTE = {
  light: { primary: "#2563eb", hot: "#ef4444", nodeFill: "#ffffff", nodeStroke: "#e2e8f0", dot: "#94a3b8", text: "#64748b" },
  dark: { primary: "#30E3CA", hot: "#FF204E", nodeFill: "#0d0e10", nodeStroke: "#3a3d42", dot: "#5a5d63", text: "#9c9c95" },
};

export function MigrationFlow({ className }: { className?: string }) {
  const reduceMotion = useReducedMotion();
  const { theme } = useTheme();
  const c = PALETTE[theme];

  return (
    <svg viewBox="0 0 900 240" className={className} role="img" aria-label="Legacy systems migrating into a target cloud">
      <defs>
        <filter id="mf-glow" x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <radialGradient id="mf-cloud-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={c.primary} stopOpacity="0.22" />
          <stop offset="100%" stopColor={c.primary} stopOpacity="0" />
        </radialGradient>
      </defs>

      <circle cx="815" cy="120" r="120" fill="url(#mf-cloud-glow)" />

      {PATHS.map((p, i) => {
        const a = LEGACY_NODES[p.from];
        const b = CLOUD_NODES[p.to];
        const id = `mf-path-${i}`;
        const d = pathD(70, a.y, b.x - 22, b.y);
        const color = p.hot ? c.hot : c.primary;
        return (
          <g key={id}>
            <path id={id} d={d} fill="none" stroke={color} strokeOpacity="0.16" strokeWidth="1.4" strokeDasharray="1 5" strokeLinecap="round" />
            {!reduceMotion && (
              <circle r={p.hot ? 3 : 2.4} fill={color} filter="url(#mf-glow)">
                <animateMotion dur={p.dur} begin={p.begin} repeatCount="indefinite">
                  <mpath href={`#${id}`} />
                </animateMotion>
              </circle>
            )}
          </g>
        );
      })}

      {LEGACY_NODES.map((n) => (
        <g key={n.label} transform={`translate(30, ${n.y})`}>
          <rect x="0" y="-13" width="76" height="26" rx="6" fill={c.nodeFill} stroke={c.nodeStroke} strokeWidth="1.2" />
          <rect x="8" y="-6" width="10" height="12" fill={c.dot} />
          <rect x="22" y="-6" width="10" height="12" fill={c.dot} />
          <rect x="36" y="-6" width="10" height="12" fill={c.dot} />
          <text x="58" y="4" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-mono-ui)" fill={c.text}>
            {n.label}
          </text>
        </g>
      ))}

      {CLOUD_NODES.map((n) => (
        <g key={n.label} transform={`translate(${n.x}, ${n.y})`}>
          <circle r="16" fill={c.nodeFill} stroke={c.primary} strokeWidth="1.4" />
          <circle r="16" fill="none" stroke={c.primary} strokeOpacity="0.35" strokeWidth="5" />
          <text x="0" y="30" textAnchor="middle" fontSize="8.5" fontFamily="var(--font-mono-ui)" fill={c.primary} letterSpacing="0.5">
            {n.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
