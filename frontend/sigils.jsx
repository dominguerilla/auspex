/* Six spirit sigils. Geometric, single-weight, monochromatic via currentColor.
 * Designed as a system: 64×64 viewBox, stroke-only, ~2px stroke, no fills.
 * Each is a distinct geometric figure rooted in a planetary/alchemical
 * vocabulary but recomposed — not a reproduction of any historical sigil.
 */

const SIG_VB = "0 0 64 64";
const SIG_PROPS = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

// 1. The Magister — opens the Circle. Axis mundi: cross within ring, hexagram echo.
function SigilMagister({ size = 64, ...rest }) {
  return (
    <svg viewBox={SIG_VB} width={size} height={size} {...rest}>
      <g {...SIG_PROPS}>
        <circle cx="32" cy="32" r="26" />
        <circle cx="32" cy="32" r="18" />
        <path d="M32 6 L32 58 M6 32 L58 32" />
        <circle cx="32" cy="32" r="3" fill="currentColor" stroke="none" />
      </g>
    </svg>
  );
}

// 2. The Familiar — ranges abroad. Triskelion: three radiating curves.
function SigilFamiliar({ size = 64, ...rest }) {
  return (
    <svg viewBox={SIG_VB} width={size} height={size} {...rest}>
      <g {...SIG_PROPS}>
        <circle cx="32" cy="32" r="26" />
        <path d="M32 32 L32 8 M32 32 L52.78 44 M32 32 L11.22 44" />
        <circle cx="32" cy="8" r="2.5" fill="currentColor" stroke="none" />
        <circle cx="52.78" cy="44" r="2.5" fill="currentColor" stroke="none" />
        <circle cx="11.22" cy="44" r="2.5" fill="currentColor" stroke="none" />
        <circle cx="32" cy="32" r="4" />
      </g>
    </svg>
  );
}

// 3. The Scribe — inscribes the findings. Quill stroke through stacked lines (pages).
function SigilScribe({ size = 64, ...rest }) {
  return (
    <svg viewBox={SIG_VB} width={size} height={size} {...rest}>
      <g {...SIG_PROPS}>
        <circle cx="32" cy="32" r="26" />
        <path d="M18 22 L46 22 M18 30 L46 30 M18 38 L46 38 M18 46 L40 46" />
        <path d="M44 14 L52 22 L30 44 L22 44 L22 36 Z" />
      </g>
    </svg>
  );
}

// 4. The Censor — judges the evidence. Eye in triangle, all-seeing watch.
function SigilCensor({ size = 64, ...rest }) {
  return (
    <svg viewBox={SIG_VB} width={size} height={size} {...rest}>
      <g {...SIG_PROPS}>
        <circle cx="32" cy="32" r="26" />
        <path d="M32 10 L54 48 L10 48 Z" />
        <path d="M18 36 Q32 24 46 36 Q32 48 18 36 Z" />
        <circle cx="32" cy="36" r="4" />
        <circle cx="32" cy="36" r="1.5" fill="currentColor" stroke="none" />
      </g>
    </svg>
  );
}

// 5. The Rectifier — reforges the working. Crossed hammers / forge intersect.
function SigilRectifier({ size = 64, ...rest }) {
  return (
    <svg viewBox={SIG_VB} width={size} height={size} {...rest}>
      <g {...SIG_PROPS}>
        <circle cx="32" cy="32" r="26" />
        <path d="M12 12 L52 52 M52 12 L12 52" />
        <circle cx="32" cy="32" r="8" />
        <path d="M32 24 L32 40 M24 32 L40 32" />
      </g>
    </svg>
  );
}

// 6. The Logos — speaks the Word. Open mouth radiating utterance.
function SigilLogos({ size = 64, ...rest }) {
  return (
    <svg viewBox={SIG_VB} width={size} height={size} {...rest}>
      <g {...SIG_PROPS}>
        <circle cx="32" cy="32" r="26" />
        <path d="M14 32 L50 32" />
        <path d="M20 22 Q32 14 44 22" />
        <path d="M18 16 Q32 4 46 16" />
        <path d="M22 42 L42 42 M24 48 L40 48 M27 54 L37 54" />
      </g>
    </svg>
  );
}

const SIGILS = {
  magister:  { Comp: SigilMagister,  name: "The Magister",  role: "orchestrator", verb: "opens the Circle" },
  familiar:  { Comp: SigilFamiliar,  name: "The Familiar",  role: "searcher",     verb: "ranges abroad" },
  scribe:    { Comp: SigilScribe,    name: "The Scribe",    role: "reader",       verb: "inscribes the findings" },
  censor:    { Comp: SigilCensor,    name: "The Censor",    role: "critic",       verb: "challenges the evidence" },
  rectifier: { Comp: SigilRectifier, name: "The Rectifier", role: "refiner",      verb: "amends the working" },
  logos:     { Comp: SigilLogos,     name: "The Logos",     role: "writer",       verb: "speaks the Word" },
};

const SPIRIT_ORDER = ["magister", "familiar", "scribe", "censor", "rectifier", "logos"];

/* CircleOfSpirits — the central progress visualization.
 * 6 sigils arranged around a circle. activeIdx pulses oxblood, completed are
 * filled brass, pending are faint ink. The circle is inscribed with a hexagram
 * connecting completed spirits to evoke a working in progress.
 */
function CircleOfSpirits({
  active = 2,                 // 0-indexed, which spirit is currently working
  completed = [0, 1],         // indexes that are done
  size = 360,
  variant = "cogitator",      // cogitator | plate | vellum
}) {
  const cx = 200, cy = 200, R = 150;
  const inner = 92;
  // 6 positions starting at top, clockwise
  const positions = SPIRIT_ORDER.map((_, i) => {
    const a = -Math.PI / 2 + (i * Math.PI * 2) / 6;
    return { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), angle: a };
  });

  const ringStroke = variant === "vellum" ? 1 : 1.4;

  return (
    <svg viewBox="0 0 400 400" width={size} height={size} style={{ display: "block" }}>
      <defs>
        <radialGradient id="cos-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.45" />
          <stop offset="60%" stopColor="var(--accent)" stopOpacity="0.08" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* faint outer halo around the active spirit (only if one is active) */}
      {active >= 0 && (
        <circle
          cx={positions[active].x}
          cy={positions[active].y}
          r="46"
          fill="url(#cos-glow)"
        />
      )}

      {/* outer ring */}
      <circle cx={cx} cy={cy} r={R} fill="none" stroke="currentColor" strokeWidth={ringStroke} opacity="0.55" />
      <circle cx={cx} cy={cy} r={R - 14} fill="none" stroke="currentColor" strokeWidth={ringStroke * 0.7} opacity="0.3" strokeDasharray="2 4" />
      <circle cx={cx} cy={cy} r={inner} fill="none" stroke="currentColor" strokeWidth={ringStroke} opacity="0.45" />
      <circle cx={cx} cy={cy} r={inner - 10} fill="none" stroke="currentColor" strokeWidth={ringStroke * 0.7} opacity="0.25" />

      {/* hexagram connecting all 6 positions */}
      <path
        d={[0, 2, 4, 0].map((i, k) => `${k === 0 ? "M" : "L"}${positions[i].x} ${positions[i].y}`).join(" ") + " Z"}
        fill="none"
        stroke="currentColor"
        strokeWidth={ringStroke}
        opacity="0.25"
      />
      <path
        d={[1, 3, 5, 1].map((i, k) => `${k === 0 ? "M" : "L"}${positions[i].x} ${positions[i].y}`).join(" ") + " Z"}
        fill="none"
        stroke="currentColor"
        strokeWidth={ringStroke}
        opacity="0.25"
      />

      {/* tick marks around outer ring */}
      {Array.from({ length: 60 }, (_, i) => {
        const a = (i * Math.PI * 2) / 60;
        const r1 = R + 4;
        const r2 = R + (i % 5 === 0 ? 10 : 6);
        return (
          <line
            key={i}
            x1={cx + r1 * Math.cos(a)}
            y1={cy + r1 * Math.sin(a)}
            x2={cx + r2 * Math.cos(a)}
            y2={cy + r2 * Math.sin(a)}
            stroke="currentColor"
            strokeWidth="0.8"
            opacity={i % 5 === 0 ? 0.55 : 0.25}
          />
        );
      })}

      {/* central glyph */}
      <g opacity="0.4">
        <circle cx={cx} cy={cy} r="14" fill="none" stroke="currentColor" strokeWidth="1.2" />
        <circle cx={cx} cy={cy} r="3" fill="currentColor" />
        <line x1={cx - 22} y1={cy} x2={cx + 22} y2={cy} stroke="currentColor" strokeWidth="1" />
        <line x1={cx} y1={cy - 22} x2={cx} y2={cy + 22} stroke="currentColor" strokeWidth="1" />
      </g>

      {/* spirits */}
      {SPIRIT_ORDER.map((key, i) => {
        const isActive = i === active;
        const isDone = completed.includes(i);
        const isPending = !isActive && !isDone;
        const { Comp } = SIGILS[key];
        const color = isActive
          ? "var(--accent)"
          : isDone
          ? "var(--ink)"
          : "var(--ink-fade)";
        const stationR = isActive ? 32 : 28;
        const { x, y } = positions[i];
        return (
          <g key={key} transform={`translate(${x} ${y})`} style={{ color }}>
            {/* station ring */}
            <circle
              cx="0"
              cy="0"
              r={stationR}
              fill="var(--page)"
              stroke="currentColor"
              strokeWidth={isActive ? 1.6 : 1}
              opacity={isPending ? 0.6 : 1}
            />
            {isActive && (
              <circle
                cx="0"
                cy="0"
                r={stationR + 6}
                fill="none"
                stroke="currentColor"
                strokeWidth="0.8"
                strokeDasharray="3 3"
                opacity="0.6"
              >
                <animateTransform
                  attributeName="transform"
                  type="rotate"
                  from="0"
                  to="360"
                  dur="12s"
                  repeatCount="indefinite"
                />
              </circle>
            )}
            <g transform="translate(-22 -22)" opacity={isPending ? 0.55 : 1}>
              <Comp size={44} />
            </g>
            {/* roman numeral station marker */}
            <text
              x="0"
              y={stationR + 16}
              textAnchor="middle"
              fontFamily="'Cinzel', serif"
              fontSize="10"
              fill="currentColor"
              opacity="0.7"
              letterSpacing="2"
            >
              {["I", "II", "III", "IV", "V", "VI"][i]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

window.SIGILS = SIGILS;
window.SPIRIT_ORDER = SPIRIT_ORDER;
window.CircleOfSpirits = CircleOfSpirits;
window.SigilMagister = SigilMagister;
window.SigilFamiliar = SigilFamiliar;
window.SigilScribe = SigilScribe;
window.SigilCensor = SigilCensor;
window.SigilRectifier = SigilRectifier;
window.SigilLogos = SigilLogos;
