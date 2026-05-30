/**
 * Number / money / percent / address formatting helpers.
 *
 * Mirrors the legacy /static/shared/utils.js MemecoUtils functions
 * one-to-one so any page migrated to Vite gets the same display
 * behavior. Page-local formatters that diverge intentionally
 * (signed pct, custom suffixes) live in their own page modules.
 */

export function numberOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function asNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function formatNumber(value, digits = 2) {
  const n = numberOrNull(value);
  if (n === null) return "N/A";
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits:
      n !== 0 && Math.abs(n) < 10 ? Math.min(digits, 2) : 0,
  });
}

export function formatPercent(value, digits = 2) {
  const n = numberOrNull(value);
  if (n === null) return "N/A";
  return `${formatNumber(n, digits)}%`;
}

/** Signed percent ("+12.34%" / "-1.23%"). Used by hero & spark tooltips. */
export function formatSignedPercent(value, digits = 2) {
  const n = numberOrNull(value);
  if (n === null) return "N/A";
  return `${n >= 0 ? "+" : ""}${formatNumber(n, digits)}%`;
}

export function formatMoney(value) {
  const n = numberOrNull(value);
  if (n === null) return "N/A";
  if (Math.abs(n) >= 1_000_000) return `$${formatNumber(n / 1_000_000, 2)}M`;
  if (Math.abs(n) >= 1_000)     return `$${formatNumber(n / 1_000, 2)}K`;
  return `$${formatNumber(n, 2)}`;
}

export function formatPrice(value) {
  const n = numberOrNull(value);
  if (n === null) return "N/A";
  if (n === 0) return "$0";
  if (n < 0.000001) return `$${n.toExponential(2)}`;
  if (n < 0.01)     return `$${n.toPrecision(4)}`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 6 })}`;
}

export function formatAgeMinutes(value) {
  const m = numberOrNull(value);
  if (m === null) return "N/A";
  if (m < 60) return `${Math.max(0, Math.round(m))}m`;
  const h = m / 60;
  if (h < 48) return `${h.toFixed(1)}h`;
  return `${(h / 24).toFixed(1)}d`;
}

/** Pretty SOL amount. Uses 4 dp for small values, 2 dp otherwise. */
export function formatSol(value) {
  const n = numberOrNull(value);
  if (n === null) return "N/A";
  return `${formatNumber(n, Math.abs(n) >= 10 ? 2 : 4)} SOL`;
}

export function shortAddress(value, head = 6, tail = 6) {
  const text = String(value || "");
  if (!text) return "N/A";
  if (text.length <= head + tail + 3) return text;
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}

export function shortWallet(value) {
  return shortAddress(value, 5, 5);
}

export function parseDetails(value) {
  if (!value) return {};
  if (typeof value === "object") return value;
  try { return JSON.parse(value); } catch { return {}; }
}
