/**
 * Wallet tier emblem.
 *
 * Wallets get a creature emblem based on their realized PnL (SOL):
 *   ≥100        TITAN     — gold halo + crown
 *   50–<100     WHALE     — whale silhouette
 *   20–<50      DOLPHIN   — dolphin
 *    5–<20      TROUT     — small fish
 *    0–<5       MINNOW    — tiny fish
 *   <0          BAGHOLDER — hand + bag, red glow
 *
 * Hand-rolled inline SVGs so the page ships with the artwork.
 * viewBox 0 0 200 200, currentColor for accent fills.
 */

export function tierForPnl(pnl) {
  const v = Number(pnl) || 0;
  if (v < 0)    return "BAGHOLDER";
  if (v < 5)    return "MINNOW";
  if (v < 20)   return "TROUT";
  if (v < 50)   return "DOLPHIN";
  if (v < 100)  return "WHALE";
  return "TITAN";
}

export function tierMetaText(tier) {
  switch (tier) {
    case "TITAN":     return "Apex tier · 100+ SOL realized profit";
    case "WHALE":     return "Mid-cap whale · 50–100 SOL profit";
    case "DOLPHIN":   return "Smart trader · 20–50 SOL profit";
    case "TROUT":     return "Active hunter · 5–20 SOL profit";
    case "MINNOW":    return "Early steps · under 5 SOL profit";
    case "BAGHOLDER": return "Underwater · realized loss";
    default:          return "";
  }
}

export function tierEmblemSvg(tier) {
  switch (tier) {
    case "TITAN":     return TITAN;
    case "WHALE":     return WHALE;
    case "DOLPHIN":   return DOLPHIN;
    case "TROUT":     return TROUT;
    case "BAGHOLDER": return BAGHOLDER;
    case "MINNOW":
    default:          return MINNOW;
  }
}

const TITAN = `
  <svg viewBox="0 0 200 200" aria-hidden="true">
    <defs>
      <radialGradient id="titanHalo" cx="50%" cy="50%" r="55%">
        <stop offset="0%" stop-color="#ffd700" stop-opacity=".55"/>
        <stop offset="100%" stop-color="#ff6600" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <circle cx="100" cy="100" r="90" fill="url(#titanHalo)"/>
    <circle cx="100" cy="100" r="68" fill="none" stroke="currentColor" stroke-width="2" opacity=".5"/>
    <path d="M55 110 L75 70 L100 100 L125 70 L145 110 L140 130 L60 130 Z" fill="currentColor" stroke="#000" stroke-width="2"/>
    <circle cx="75"  cy="68" r="6" fill="#ffd700" stroke="#000" stroke-width="1.5"/>
    <circle cx="100" cy="98" r="6" fill="#ffd700" stroke="#000" stroke-width="1.5"/>
    <circle cx="125" cy="68" r="6" fill="#ffd700" stroke="#000" stroke-width="1.5"/>
    <rect x="58" y="132" width="84" height="8" fill="currentColor" rx="2"/>
  </svg>
`;

const WHALE = `
  <svg viewBox="0 0 200 200" aria-hidden="true">
    <defs>
      <radialGradient id="whaleHalo" cx="50%" cy="50%" r="55%">
        <stop offset="0%" stop-color="#ff8800" stop-opacity=".35"/>
        <stop offset="100%" stop-color="#ff6600" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <circle cx="100" cy="100" r="90" fill="url(#whaleHalo)"/>
    <path d="M30 110 Q50 70 110 80 Q150 85 165 110 Q150 130 110 130 Q70 132 50 122 L20 130 L30 110 Z"
          fill="currentColor" stroke="#000" stroke-width="2"/>
    <path d="M150 88 L185 70 L175 105 Z" fill="currentColor" stroke="#000" stroke-width="2"/>
    <circle cx="55" cy="105" r="3" fill="#000"/>
    <path d="M70 70 Q72 55 80 50 M80 70 Q82 55 90 50 M90 70 Q92 55 100 50"
          fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" opacity=".55"/>
  </svg>
`;

const DOLPHIN = `
  <svg viewBox="0 0 200 200" aria-hidden="true">
    <circle cx="100" cy="100" r="90" fill="rgba(255,102,0,.10)"/>
    <path d="M30 130 Q60 60 130 80 Q170 90 175 130 Q150 140 130 130 Q90 145 50 140 Z"
          fill="currentColor" stroke="#000" stroke-width="2"/>
    <path d="M120 70 Q140 40 145 80 Z" fill="currentColor" stroke="#000" stroke-width="2"/>
    <path d="M170 130 L195 110 L185 140 Z" fill="currentColor" stroke="#000" stroke-width="2"/>
    <circle cx="55" cy="115" r="3" fill="#000"/>
    <path d="M50 130 Q70 138 90 130" fill="none" stroke="#000" stroke-width="2" opacity=".4"/>
  </svg>
`;

const TROUT = `
  <svg viewBox="0 0 200 200" aria-hidden="true">
    <circle cx="100" cy="100" r="90" fill="rgba(255,102,0,.07)"/>
    <ellipse cx="100" cy="105" rx="65" ry="28" fill="currentColor" stroke="#000" stroke-width="2"/>
    <path d="M155 105 L185 80 L185 130 Z" fill="currentColor" stroke="#000" stroke-width="2"/>
    <circle cx="60" cy="100" r="3" fill="#000"/>
    <path d="M70 105 Q90 92 110 105 Q130 118 150 105" fill="none" stroke="#000" stroke-width="1.5" opacity=".35"/>
    <circle cx="115" cy="98"  r="2" fill="#000" opacity=".5"/>
    <circle cx="130" cy="110" r="2" fill="#000" opacity=".5"/>
    <circle cx="100" cy="115" r="2" fill="#000" opacity=".5"/>
  </svg>
`;

const MINNOW = `
  <svg viewBox="0 0 200 200" aria-hidden="true">
    <circle cx="100" cy="100" r="90" fill="rgba(160,160,160,.08)"/>
    <ellipse cx="100" cy="110" rx="40" ry="16" fill="currentColor" stroke="#000" stroke-width="2"/>
    <path d="M135 110 L155 95 L155 125 Z" fill="currentColor" stroke="#000" stroke-width="2"/>
    <circle cx="78" cy="106" r="2.5" fill="#000"/>
    <circle cx="50" cy="80"  r="3"   fill="none" stroke="currentColor" stroke-width="1.5" opacity=".5"/>
    <circle cx="60" cy="65"  r="2"   fill="none" stroke="currentColor" stroke-width="1.5" opacity=".4"/>
    <circle cx="45" cy="62"  r="1.5" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".3"/>
  </svg>
`;

const BAGHOLDER = `
  <svg viewBox="0 0 200 200" aria-hidden="true">
    <defs>
      <radialGradient id="bagHalo" cx="50%" cy="60%" r="60%">
        <stop offset="0%" stop-color="#ff4d5e" stop-opacity=".35"/>
        <stop offset="100%" stop-color="#ff4d5e" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <circle cx="100" cy="110" r="90" fill="url(#bagHalo)"/>
    <path d="M70 70 L130 70 L150 160 Q100 175 50 160 Z" fill="currentColor" stroke="#000" stroke-width="2"/>
    <path d="M75 70 Q100 50 125 70" fill="none" stroke="#000" stroke-width="3"/>
    <text x="100" y="130" text-anchor="middle" fill="#000" font-size="36" font-weight="900"
          font-family="ui-monospace, Menlo, monospace" opacity=".7">$</text>
    <circle cx="40"  cy="170" r="2"   fill="currentColor" opacity=".7"/>
    <circle cx="160" cy="172" r="2.5" fill="currentColor" opacity=".7"/>
    <circle cx="55"  cy="180" r="1.5" fill="currentColor" opacity=".55"/>
  </svg>
`;
