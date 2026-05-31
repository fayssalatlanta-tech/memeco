/**
 * Memeco — CASE FILE / TOKEN DETAIL (Vite-built version).
 *
 * Same data and visual identity as app/static/token_detail.html.
 * Renders the identity hero with logo + change-signals diff strip,
 * KPI metric grid, the 12-card Decision Dossier, the horizontal
 * Token Timeline, and four wallet/holder/relationship tables.
 */

import "../../styles/tokens.css";
import "../../styles/cyberpunk.css";
import "./token.css";

import { formatDate } from "../../lib/time.js";
import { mount, escapeHtml } from "../../lib/dom.js";
import {
  numberOrNull, formatPercent, parseDetails, shortAddress as sharedShortAddress,
} from "../../lib/format.js";

import { BrandBar } from "../../components/BrandBar.js";

const appEl = document.querySelector("#app");
let currentToken = null;

const asNumeric = numberOrNull;
// token_detail uses 6/4 split, not the shared default 6/6.
const shortAddress = (value) => sharedShortAddress(value, 6, 4);

function attr(value) { return escapeHtml(value); }

function params() {
  return new URLSearchParams(window.location.search);
}

// ---- Local formatters (intentionally diverge from format.js):
//   formatNumber  — no minimumFractionDigits ("7.5" stays "7.5").
//   formatPercent — always 2 decimals, including for 0 ("0.00%").
function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "N/A";
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}
function formatPercent2dp(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  return `${n.toFixed(2)}%`;
}

function validDate(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || seconds === "") return "N/A";
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "N/A";
  const abs = Math.abs(value);
  let label = "";
  if (abs < 60)        label = `${Math.round(abs)}s`;
  else if (abs < 3600) label = `${Math.round(abs / 60)}m`;
  else                 label = `${(abs / 3600).toFixed(1)}h`;
  return value < 0 ? `${label} before` : label;
}

function formatRelativeTime(value, origin) {
  if (!value) return "N/A";
  if (!origin) return formatDate(value);
  const d = new Date(value);
  const o = new Date(origin);
  if (Number.isNaN(d.getTime()) || Number.isNaN(o.getTime())) return formatDate(value);
  return formatDuration((d.getTime() - o.getTime()) / 1000);
}

function formatSol(value, digits = 4) {
  if (value === null || value === undefined || value === "") return "N/A";
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  return `${n.toLocaleString(undefined, { maximumFractionDigits: digits })} SOL`;
}

const parseJson = (value, fallback) => {
  if (!value) return fallback;
  if (typeof value === "object") return value;
  try { return JSON.parse(value); } catch { return fallback; }
};

const normalizeList = (value) => {
  const parsed = parseJson(value, []);
  return Array.isArray(parsed) ? parsed : [];
};

// ---- Decision class helpers ---------------------------------------

function badgeClass(status) {
  if (!status) return "";
  if (status.includes("PASS"))   return "pass";
  if (status.includes("REJECT")) return "reject";
  if (status.includes("WAIT"))   return "wait";
  return "";
}
function labelClass(label) {
  if (label === "SMART_WALLET") return "good";
  if (["SNIPER","FRESH_WALLET","DUMPER","DEV_RELATED","BOT","TOKEN_DISTRIBUTION","SOL_FUNDER","TOKEN_LINK","SOL_LINK"].includes(label)) return "bad";
  if (label === "WHALE") return "warn";
  return "";
}
function metricClass(label, value) {
  const t = String(value || "");
  if (label === "Manipulation") {
    if (t.includes("DANGER")) return "danger";
    if (t.includes("WARNING") || t.includes("UNKNOWN")) return "warning";
    if (t.includes("PASS")) return "pass";
  }
  if (label === "Final") {
    if (t.includes("REJECT")) return "danger";
    if (t.includes("WAIT") || t.includes("HIGH_RISK")) return "warning";
    if (t.includes("PASS")) return "pass";
  }
  return "";
}
function walletRowClass(labels, score) {
  const bad = ["SNIPER","FRESH_WALLET","DUMPER","DEV_RELATED","BOT"];
  const n = Number(score || 0);
  if (labels.some((l) => bad.includes(l)) || n <= -5) return "suspicious-row";
  if (labels.includes("WHALE") || n < 0)              return "warning-row";
  return "";
}
function scoreBadge(score) {
  const n = Number(score || 0);
  const cls = n <= -5 ? "bad" : n < 0 ? "warn" : "";
  return `<span class="score-badge ${cls}">${escapeHtml(score ?? "N/A")}</span>`;
}
function profitStateClass(state) {
  const t = String(state || "UNKNOWN").toLowerCase();
  if (["profit","unrealized"].includes(t)) return t;
  if (t === "loss") return "loss";
  return "unknown";
}
function profitStateBadge(state) {
  const t = String(state || "UNKNOWN");
  return `<span class="profit-state ${profitStateClass(t)}">${escapeHtml(t)}</span>`;
}
function relationshipClass(type) {
  if (["SOL_FUNDER","TOKEN_DISTRIBUTION","TOKEN_LINK","SOL_LINK"].includes(type)) return "suspicious";
  return "";
}
function decisionTone(status, pass) {
  const t = String(status || "");
  if (pass === false || t.includes("REJECT") || t.includes("DANGER")) return "danger";
  if (t.includes("WAIT") || t.includes("WARNING") || t.includes("UNKNOWN") || t.includes("HIGH_RISK")) return "warning";
  if (pass === true || t.includes("PASS")) return "pass";
  if (!t || t === "PENDING") return "pending";
  return "";
}
function passFromStatus(status) {
  const t = String(status || "");
  if (t.includes("PASS")) return true;
  if (t.includes("REJECT") || t.includes("DANGER") || t.includes("HIGH_RISK")) return false;
  return null;
}
function warningText(w) {
  if (!w) return "";
  if (typeof w === "string") return w;
  if (typeof w === "object") {
    return [w.name, w.level, w.message || w.reason].filter(Boolean).join(" - ");
  }
  return String(w);
}

function insiderProbabilityHtml(details) {
  const score = Number(details.insider_probability_score ?? 0);
  const level = String(details.insider_probability_level || "LOW");
  const reasons = normalizeList(details.insider_probability_reasons);
  const title = reasons.length ? reasons.join(" | ") : "No strong insider signal";
  return `<span class="probability-badge ${level.toLowerCase()}" title="${attr(title)}">${score}/100 ${escapeHtml(level)}</span>`;
}
function liquidityTrapHtml(details) {
  const status = String(details.liquidity_trap_status || "LIQUIDITY_TRAP_UNKNOWN");
  const score = Number(details.liquidity_trap_score ?? 0);
  const reason = details.liquidity_trap_reason || "";
  const warnings = normalizeList(details.liquidity_trap_warnings);
  const lpLock = details.lp_lock || {};
  let level = "LOW";
  if (status.includes("CRITICAL")) level = "CRITICAL";
  else if (status.includes("HIGH")) level = "HIGH";
  else if (status.includes("MEDIUM") || status.includes("UNKNOWN")) level = "MEDIUM";
  const title = [reason, lpLock.lp_reason, ...warnings].filter(Boolean).join(" | ");
  return `<span class="probability-badge ${level.toLowerCase()}" title="${attr(title)}">${score}/100 ${escapeHtml(level)}</span>`;
}
function devAuditHtml(details) {
  const status = String(details.dev_audit_status || "DEV_UNKNOWN");
  const sold = Number(details.dev_sold_token_amount || 0);
  const out = Number(details.dev_total_token_out || 0);
  const title = [
    details.dev_audit_reason,
    details.dev_wallet_address ? `Dev: ${details.dev_wallet_address}` : "",
    `Sold: ${sold.toLocaleString()}`,
    `Out: ${out.toLocaleString()}`,
  ].filter(Boolean).join(" | ");
  let level = "medium";
  if (status === "DEV_HOLDING") level = "low";
  if (["DEV_SOLD_PARTIAL","DEV_SOLD_OUT","DEV_TRANSFERRED_TOKENS","DEV_NO_BALANCE"].includes(status)) level = "high";
  return `<span class="probability-badge ${level}" title="${attr(title)}">${escapeHtml(status.replace("DEV_", ""))}</span>`;
}

// ---- Change-signals snapshots -------------------------------------

function tokenSnapshot(token) {
  const details = parseJson(token.details, {});
  return {
    token_address: token.token_address,
    run_id: token.run_id,
    token_id: token.token_id,
    final_watchlist_status: token.final_watchlist_status || "",
    final_watchlist_reason: token.final_watchlist_reason || "",
    market_filter_status: token.market_filter_status || "",
    contract_risk_status: token.contract_risk_status || "",
    wallet_status: token.wallet_status || "",
    cluster_status: token.cluster_status || "",
    manipulation_status: token.manipulation_status || "",
    manipulation_score: asNumeric(token.manipulation_score),
    insider_probability_score: asNumeric(details.insider_probability_score),
    insider_probability_level: details.insider_probability_level || "",
    liquidity_trap_score: asNumeric(details.liquidity_trap_score),
    liquidity_trap_status: details.liquidity_trap_status || "",
    shadow_dev_score: asNumeric(details.shadow_dev_score),
    dev_flow_status: details.dev_flow_status || "",
    dev_proxy_dump_count: asNumeric(details.dev_proxy_dump_count),
    dev_splitter_count: asNumeric(details.dev_splitter_count),
    dev_audit_status: details.dev_audit_status || "",
    dev_sold_token_amount: asNumeric(details.dev_sold_token_amount),
    dev_total_token_out: asNumeric(details.dev_total_token_out),
    liquidity_usd: asNumeric(details.liquidity_usd),
    market_cap_usd: asNumeric(details.market_cap_usd),
    dex_active_boosts: asNumeric(token.dex_active_boosts),
    dex_paid_order_count: asNumeric(token.dex_paid_order_count),
    updated_at: token.created_at || "",
  };
}
const snapshotKey = (addr) => `token-refresh-before:${addr}`;

function formatSnapshotValue(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  if (typeof value === "number") return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(value);
}

function changeTone(label, before, after) {
  const riskUp = ["Insider Probability","Liquidity Trap","Shadow Dev Score","Manipulation Score","Dev Sold","Dev Out","Proxy Dumps","Splitters"];
  if (typeof before === "number" && typeof after === "number") {
    if (after === before) return "";
    const ri = riskUp.includes(label);
    return after > before ? (ri ? "bad" : "good") : (ri ? "good" : "warn");
  }
  const t = String(after || "");
  if (t.includes("REJECT") || t.includes("DANGER") || t.includes("SOLD") || t.includes("DUMP")) return "bad";
  if (t.includes("WARNING") || t.includes("WAIT") || t.includes("UNKNOWN") || t.includes("HIGH")) return "warn";
  if (t.includes("PASS") || t.includes("LOW") || t.includes("HOLDING")) return "good";
  return "";
}
function buildChanges(before, after) {
  const fields = [
    ["Final","final_watchlist_status"], ["Reason","final_watchlist_reason"],
    ["Insider Probability","insider_probability_score"], ["Insider Level","insider_probability_level"],
    ["Liquidity Trap","liquidity_trap_score"], ["Shadow Dev Score","shadow_dev_score"],
    ["Dev Flow","dev_flow_status"], ["Proxy Dumps","dev_proxy_dump_count"], ["Splitters","dev_splitter_count"],
    ["Dev Audit","dev_audit_status"], ["Dev Sold","dev_sold_token_amount"], ["Dev Out","dev_total_token_out"],
    ["Wallet","wallet_status"], ["Cluster","cluster_status"], ["Manipulation","manipulation_status"],
    ["Manipulation Score","manipulation_score"],
    ["Liquidity","liquidity_usd"], ["Market Cap","market_cap_usd"],
    ["DEX Boosts","dex_active_boosts"], ["DEX Orders","dex_paid_order_count"],
  ];
  return fields.map(([label, key]) => {
    const b = before[key]; const a = after[key];
    if (JSON.stringify(b) === JSON.stringify(a)) return null;
    return { label, before: b, after: a, tone: changeTone(label, b, a) };
  }).filter(Boolean);
}

// ---- Render helpers ------------------------------------------------

function copyIcon() {
  return `
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" stroke-width="2"></rect>
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="currentColor" stroke-width="2"></path>
    </svg>
  `;
}
function fallbackLogoHtml(symbol) {
  return `<span class="logo logo-fallback">${escapeHtml((symbol || "?").slice(0, 2).toUpperCase())}</span>`;
}
function walletCellHtml(address) {
  const safe = attr(address || "");
  return `
    <div class="wallet-cell">
      <div class="wallet-address" title="${safe}">${escapeHtml(address || "N/A")}</div>
      ${address ? `<button class="copy-small copy-button" type="button" aria-label="Copy wallet address" title="Copy wallet address" data-address="${safe}">${copyIcon()}</button>` : ""}
    </div>
  `;
}

async function copyAddress(address, button) {
  try { await navigator.clipboard.writeText(address); }
  catch {
    const ta = document.createElement("textarea");
    ta.value = address; ta.style.position = "fixed"; ta.style.left = "-9999px";
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  button.classList.add("copied");
  button.setAttribute("aria-label", "Copied");
  setTimeout(() => {
    button.classList.remove("copied");
    button.setAttribute("aria-label", "Copy address");
  }, 1200);
}

function formatDexAdsText(token) {
  const ab = Number(token.dex_active_boosts || 0);
  const pc = Number(token.dex_paid_order_count || 0);
  const bc = Number(token.dex_boost_order_count || 0);
  const ot = parseJson(token.dex_paid_order_types, []);
  const tl = Array.isArray(ot) ? ot.map((t) => String(t || "").replace("tokenProfile", "Profile")) : [];
  if (ab >= 500) return `Golden ticker ${ab}`;
  if (ab > 0)    return `Active boost ${ab}`;
  if (bc > 0)    return `Boost order (${bc})`;
  if (pc > 0 || tl.length) return tl.length ? tl.join(", ") : `Paid order (${pc})`;
  return "None";
}

function earliestWallet(wallets, predicate) {
  const candidates = wallets
    .filter((w) => w.first_entry_at && (!predicate || predicate(w)))
    .sort((l, r) => new Date(l.first_entry_at) - new Date(r.first_entry_at));
  const nonTrunc = candidates.filter((w) => !parseJson(w.details, {}).history_may_be_truncated);
  return nonTrunc[0] || candidates[0] || null;
}
function earliestExitWallet(wallets, threshold = 0.65) {
  const candidates = wallets
    .filter((w) => {
      const ti = Number(w.total_token_in || 0);
      const to = Number(w.total_token_out || 0);
      const d = parseJson(w.details, {});
      return d.first_exit_at && ti > 0 && to / ti >= threshold;
    })
    .sort((l, r) => {
      const ld = parseJson(l.details, {}); const rd = parseJson(r.details, {});
      return new Date(ld.first_exit_at) - new Date(rd.first_exit_at);
    });
  const nonTrunc = candidates.filter((w) => !parseJson(w.details, {}).history_may_be_truncated);
  return nonTrunc[0] || candidates[0] || null;
}

// ---- Render functions ---------------------------------------------

function renderShell(statusText) {
  const right = `<span class="td-status" id="status">${escapeHtml(statusText || "Loading...")}</span>`;
  return `
    ${BrandBar({ name: "CASE FILE", tag: "TOKEN INTELLIGENCE · DECISION DOSSIER", extraActive: "TOKEN", right })}
    <section class="td-hero">
      <div class="td-hero-main" id="tokenHead"></div>
      <aside class="td-hero-side change-panel" id="changePanel" hidden>
        <header class="cy-section-head">
          <h2>CHANGE SIGNALS</h2>
          <div class="cy-section-note" id="changeNote">Diffs from the previous refresh appear here.</div>
        </header>
        <div class="change-grid" id="changeGrid"></div>
      </aside>
    </section>
    <section class="td-hud" id="metrics"></section>
    <section class="td-panel td-dossier">
      <header class="cy-section-head">
        <h2>DECISION DOSSIER</h2>
        <div class="cy-section-note">Each pipeline stage as an evidence card. Tone says PASS / WARN / FAIL / UNKNOWN at a glance.</div>
      </header>
      <div class="decision-tree" id="decisionTree"></div>
    </section>
    <section class="td-panel td-timeline-block">
      <header class="cy-section-head">
        <h2>TOKEN TIMELINE</h2>
        <div class="cy-section-note">Observed events between pair creation and the latest decision.</div>
      </header>
      <div class="timeline" id="tokenTimeline"></div>
    </section>
    <section class="td-panel">
      <header class="cy-section-head">
        <h2>WALLET INTELLIGENCE</h2>
        <div class="cy-section-note">Top holders enriched with labels, entry timing, and net flow.</div>
      </header>
      <div class="td-table-wrap">
        <table>
          <thead><tr>
            <th>Rank</th><th>Wallet</th><th>Holder %</th><th>Labels</th><th>Label Reason</th>
            <th>Score</th><th>Entry</th><th>From Launch</th>
            <th>In</th><th>Out</th><th>Net</th><th>Txs</th><th>Funding Source</th>
          </tr></thead>
          <tbody id="walletRows"></tbody>
        </table>
      </div>
    </section>
    <section class="td-panel">
      <header class="cy-section-head">
        <h2>EARLY BUYER PROFIT MAP</h2>
        <div class="cy-section-note">Tracked early holders' realized PnL inferred from observed swaps.</div>
      </header>
      <div class="profit-map" id="earlyBuyerSummary"></div>
      <div class="td-table-wrap">
        <table>
          <thead><tr>
            <th>#</th><th>Wallet</th><th>Entry</th><th>From Launch</th><th>Status</th><th>Profit State</th>
            <th>In</th><th>Out</th><th>Net</th><th>SOL Spent</th><th>SOL Received</th><th>Realized PnL</th><th>Labels</th>
          </tr></thead>
          <tbody id="earlyBuyerRows"></tbody>
        </table>
      </div>
    </section>
    <section class="td-panel">
      <header class="cy-section-head">
        <h2>TOP HOLDERS</h2>
        <div class="cy-section-note">Concentration as reported by the contract risk source.</div>
      </header>
      <div class="td-table-wrap">
        <table>
          <thead><tr>
            <th>Rank</th><th>Wallet</th><th>Amount</th><th>Percent</th><th>Source</th>
          </tr></thead>
          <tbody id="holderRows"></tbody>
        </table>
      </div>
    </section>
    <section class="td-panel">
      <header class="cy-section-head">
        <h2>WALLET RELATIONSHIPS</h2>
        <div class="cy-section-note">Direct SOL or token edges between top holders, plus dump events.</div>
      </header>
      <div class="td-table-wrap">
        <table>
          <thead><tr>
            <th>Type</th><th>From</th><th>To</th><th>Amount</th><th>Time</th><th>Signature</th>
          </tr></thead>
          <tbody id="relationshipRows"></tbody>
        </table>
      </div>
    </section>
  `;
}

function renderToken(token) {
  const details = parseJson(token.details, {});
  const summary = parseJson(token.intelligence_summary, {});
  const dexEntry = token.pair_created_at ? formatDate(token.pair_created_at) : "N/A";
  const logo = token.logo_url
    ? `<img class="logo" src="${attr(token.logo_url)}" alt="" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'), { className: 'logo logo-fallback', textContent: '${attr((token.symbol || "?").slice(0, 2).toUpperCase())}' }))">`
    : fallbackLogoHtml(token.symbol);

  document.querySelector("#tokenHead").innerHTML = `
    <div class="token-main">
      ${logo}
      <div>
        <h1>${escapeHtml(token.symbol || "Unknown")} <span class="muted">${token.name ? escapeHtml(token.name) : ""}</span></h1>
        <div class="address-line">
          <div class="address" title="${attr(token.token_address || "")}">${escapeHtml(token.token_address || "")}</div>
          <button class="copy-button" type="button" aria-label="Copy token address" title="Copy token address" data-address="${attr(token.token_address || "")}">${copyIcon()}</button>
        </div>
        <div class="dex-entry-note" title="${attr(token.pair_created_at || "")}">DEX entry: ${escapeHtml(dexEntry)}</div>
      </div>
    </div>
    <div class="token-actions">
      <button id="refreshTokenButton" type="button" data-address="${attr(token.token_address || "")}">Refresh Analysis</button>
      ${token.pair_url ? `<a class="external-link" href="${attr(token.pair_url)}" target="_blank" rel="noopener">DexScreener</a>` : ""}
    </div>
  `;

  const metrics = [
    ["Final", `<span class="badge ${badgeClass(token.final_watchlist_status || "")}">${escapeHtml(token.final_watchlist_status || "N/A")}</span>`],
    ["Reason", escapeHtml(token.final_watchlist_reason || "N/A")],
    ["Insider Probability", insiderProbabilityHtml(details)],
    ["Liquidity Trap", liquidityTrapHtml(details)],
    ["LP Lock", escapeHtml((details.lp_lock || {}).lp_lock_status || "Unknown")],
    ["Dev Audit", devAuditHtml(details)],
    ["Market", escapeHtml(token.market_filter_status || "N/A")],
    ["Contract", escapeHtml(token.contract_risk_status || "Pending")],
    ["Wallet", escapeHtml(token.wallet_status || "Pending")],
    ["Cluster", escapeHtml(token.cluster_status || "Pending")],
    ["Manipulation", escapeHtml(token.manipulation_status || "Pending")],
    ["Manipulation Score", `${formatNumber(token.manipulation_score, 0)}/10`],
    ["Dev Sold", formatNumber(details.dev_sold_token_amount || 0, 2)],
    ["Dev Out", formatNumber(details.dev_total_token_out || 0, 2)],
    ["Smart Wallets", formatNumber(summary.smart_wallets || 0, 0)],
    ["Early Buyers", formatNumber(summary.early_buyers || 0, 0)],
    ["Early Holding", formatNumber(summary.early_holding || 0, 0)],
    ["Early Profitable", formatNumber(summary.early_profitable || 0, 0)],
    ["Fresh Wallets", formatNumber(summary.fresh_wallets || 0, 0)],
    ["Snipers", formatNumber(summary.snipers || 0, 0)],
    ["Dumpers", formatNumber(summary.dumpers || 0, 0)],
    ["Dev Related", formatNumber(summary.dev_related || 0, 0)],
    ["Dex Ads", escapeHtml(formatDexAdsText(token))],
    ["Top Holder", formatPercent2dp(token.top_holder_percent)],
    ["Top 10", formatPercent2dp(token.top10_holders_percent)],
    ["Liquidity", `$${formatNumber(details.liquidity_usd)}`],
    ["Market Cap", `$${formatNumber(details.market_cap_usd)}`],
    ["Pair", escapeHtml(token.dex_id || "N/A")],
    ["Updated", formatDate(token.created_at)],
  ];

  document.querySelector("#metrics").innerHTML = metrics.map(([label, value]) => `
    <article class="metric ${metricClass(label, value)}">
      <div class="metric-label">${label}</div>
      <div class="metric-value">${value || "N/A"}</div>
    </article>
  `).join("");
}

function renderChangeSignals(token) {
  const beforeRaw = localStorage.getItem(snapshotKey(token.token_address));
  const panelEl = document.querySelector("#changePanel");
  const gridEl = document.querySelector("#changeGrid");
  const noteEl = document.querySelector("#changeNote");
  if (!beforeRaw) {
    panelEl.hidden = true;
    gridEl.innerHTML = "";
    return;
  }
  let before = null;
  try { before = JSON.parse(beforeRaw); }
  catch { localStorage.removeItem(snapshotKey(token.token_address)); return; }

  const after = tokenSnapshot(token);
  if (before.run_id === after.run_id) return;

  const changes = buildChanges(before, after);
  panelEl.hidden = false;
  noteEl.textContent = changes.length
    ? `Compared run #${before.run_id || "old"} to run #${after.run_id || "new"}`
    : `No important change detected after refresh. Run #${after.run_id || "new"} is current.`;
  gridEl.innerHTML = changes.length
    ? changes.slice(0, 9).map((c) => `
      <article class="change-item ${c.tone}">
        <div class="change-label">${escapeHtml(c.label)}</div>
        <div class="change-value">${escapeHtml(formatSnapshotValue(c.before))} -> ${escapeHtml(formatSnapshotValue(c.after))}</div>
      </article>
    `).join("")
    : `<article class="change-item good"><div class="change-label">Stable</div><div class="change-value">No key signal changed.</div></article>`;

  localStorage.removeItem(snapshotKey(token.token_address));
}

function firstReason(...values) {
  return values.map((v) => String(v || "").trim()).find(Boolean) || "No detailed reason stored yet.";
}

function renderDecisionTree(token) {
  const details = parseJson(token.details, {});
  const intelligenceReasons = normalizeList(details.intelligence_reasons);
  const steps = [
    { title: "Market Filter",       status: token.market_filter_status || "PENDING",          pass: token.market_filter_pass,
      reason: firstReason(details.market_filter_reason, token.final_watchlist_status === "WATCHLIST_REJECT_MARKET" ? token.final_watchlist_reason : ""),
      warnings: normalizeList(details.market_warnings) },
    { title: "Contract Risk",       status: token.contract_risk_status || "PENDING",          pass: token.contract_risk_pass,
      reason: firstReason(details.contract_risk_reason, token.final_watchlist_status === "WATCHLIST_REJECT_CONTRACT" ? token.final_watchlist_reason : ""),
      warnings: normalizeList(details.contract_warnings) },
    { title: "Liquidity Filter",    status: details.liquidity_status || "PENDING",            pass: passFromStatus(details.liquidity_status),
      reason: firstReason(details.liquidity_reason, token.final_watchlist_status === "WATCHLIST_REJECT_LIQUIDITY" ? token.final_watchlist_reason : ""),
      warnings: normalizeList(details.liquidity_warnings) },
    { title: "Liquidity Trap",      status: `${details.liquidity_trap_score ?? 0}/100 ${details.liquidity_trap_status || "LIQUIDITY_TRAP_UNKNOWN"}`,
      pass: Number(details.liquidity_trap_score ?? 0) < 50,
      reason: firstReason(details.liquidity_trap_reason, "No strong liquidity trap pattern detected"),
      warnings: normalizeList(details.liquidity_trap_warnings) },
    { title: "Wallet Analysis",     status: token.wallet_status || details.wallet_status || "PENDING", pass: token.wallet_pass,
      reason: firstReason(details.wallet_reason, token.final_watchlist_status === "WATCHLIST_REJECT_WALLET" ? token.final_watchlist_reason : ""),
      warnings: normalizeList(details.wallet_warnings) },
    { title: "Cluster Analysis",    status: token.cluster_status || details.cluster_status || "PENDING", pass: token.cluster_pass,
      reason: firstReason(details.cluster_reason, token.final_watchlist_status === "WATCHLIST_REJECT_CLUSTER" ? token.final_watchlist_reason : ""),
      warnings: normalizeList(details.cluster_warnings) },
    { title: "Wallet Manipulation", status: token.manipulation_status || details.manipulation_status || "PENDING", pass: token.manipulation_pass,
      reason: firstReason(details.manipulation_reason, token.manipulation_reason, token.final_watchlist_status === "WATCHLIST_REJECT_MANIPULATION" ? token.final_watchlist_reason : ""),
      warnings: normalizeList(details.manipulation_warnings) },
    { title: "Dev Wallet Audit",    status: details.dev_audit_status || "DEV_UNKNOWN",        pass: details.dev_audit_pass,
      reason: firstReason(details.dev_audit_reason, "Developer audit has no result yet"),
      warnings: normalizeList(details.dev_audit_warnings) },
    { title: "Dev Wallet Flow",     status: `${details.shadow_dev_score ?? 0}/100 ${details.dev_flow_status || "DEV_FLOW_UNKNOWN"}`, pass: details.dev_flow_pass,
      reason: firstReason(details.dev_flow_reason, "Developer flow analysis has no result yet"),
      warnings: normalizeList(details.dev_flow_warnings) },
    { title: "Wallet Intelligence", status: details.intelligence_status || "PENDING",         pass: passFromStatus(details.intelligence_status),
      reason: firstReason(intelligenceReasons.join(" | ")),
      warnings: intelligenceReasons },
    { title: "Insider Probability", status: `${details.insider_probability_score ?? 0}/100 ${details.insider_probability_level || "LOW"}`,
      pass: Number(details.insider_probability_score ?? 0) < 50,
      reason: firstReason(normalizeList(details.insider_probability_reasons).join(" | "), "No strong insider signal"),
      warnings: normalizeList(details.insider_probability_reasons) },
    { title: "Final Decision",      status: token.final_watchlist_status || "PENDING",        pass: token.final_watchlist_pass,
      reason: firstReason(token.final_watchlist_reason),
      warnings: normalizeList(details.high_risk_reasons).slice(0, 8) },
  ];

  document.querySelector("#decisionTree").innerHTML = steps.map((step) => {
    const tone = decisionTone(step.status, step.pass);
    const warnings = step.warnings.map(warningText).filter(Boolean)
      .filter((t, i, l) => l.indexOf(t) === i).slice(0, 4);
    return `
      <article class="decision-step ${tone}">
        <div class="decision-step-head">
          <div class="decision-step-title">${escapeHtml(step.title)}</div>
          <div class="decision-step-status">${escapeHtml(step.status || "PENDING")}</div>
        </div>
        <div class="decision-step-reason">${escapeHtml(step.reason)}</div>
        ${warnings.length ? `<ul class="decision-step-list">${warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul>` : ""}
      </article>
    `;
  }).join("");
}

function renderTokenTimeline(token, wallets) {
  const launchAt = token.pair_created_at || token.first_price_snapshot_at || token.dexscreener_first_seen_at;
  const originLabel = token.pair_created_at ? "pair creation time" : "first reliable stored timestamp";
  const firstTrackedEntry = earliestWallet(wallets);
  const firstSniper = earliestWallet(wallets, (w) => normalizeList(w.labels).includes("SNIPER"));
  const firstMajorExit = earliestExitWallet(wallets);
  const hasDexAd = Number(token.dex_active_boosts || 0) > 0
    || Number(token.dex_paid_order_count || 0) > 0
    || Number(token.dex_boost_order_count || 0) > 0;
  const events = [];
  function add(e) {
    const d = validDate(e.time); if (!d) return;
    events.push({ ...e, date: d });
  }
  if (token.pair_created_at) add({
    title: "DEX Entry / Bonding Complete", time: token.pair_created_at, tone: "pass",
    body: `Official selected DEX pair was created on ${token.dex_id || "the selected DEX"}. Because bonding-only pairs are skipped, this is the system's DEX entry timestamp.`,
  });
  add({ title: "First DexScreener Profile Snapshot", time: token.dexscreener_first_seen_at, tone: "pass",
        body: "First stored token profile snapshot from DexScreener in this local database." });
  add({ title: "First Stored Price Snapshot", time: token.first_price_snapshot_at, tone: "pass",
        body: "First stored price/liquidity snapshot for the selected pair." });
  if (firstTrackedEntry) {
    const d = parseJson(firstTrackedEntry.details, {});
    const reliability = d.history_may_be_truncated ? " Wallet history is truncated, so this is the earliest observed entry in the fetched holder window." : "";
    add({ title: "First Tracked Holder Entry", time: firstTrackedEntry.first_entry_at,
          tone: d.history_may_be_truncated ? "warning" : "pass",
          body: `${shortAddress(firstTrackedEntry.wallet_address)} entered ${formatRelativeTime(firstTrackedEntry.first_entry_at, launchAt)} from ${originLabel}. This is from tracked top-holder wallets, not all buyers.${reliability}` });
  }
  if (firstSniper) {
    const d = parseJson(firstSniper.details, {});
    const reliability = d.history_may_be_truncated ? " Wallet history is truncated; sniper label is based on observed token entry." : "";
    add({ title: "First Tracked Sniper", time: firstSniper.first_entry_at, tone: "danger",
          body: `${shortAddress(firstSniper.wallet_address)} entered ${formatDuration(firstSniper.seconds_from_launch)} from pair creation time.${reliability}` });
  }
  if (firstMajorExit) {
    const d = parseJson(firstMajorExit.details, {});
    const firstExitAt = d.first_exit_at;
    const reliability = d.history_may_be_truncated ? " Wallet history is truncated, so earlier exits may exist outside the fetched window." : "";
    const ti = Number(firstMajorExit.total_token_in || 0);
    const to = Number(firstMajorExit.total_token_out || 0);
    const sellRatio = ti > 0 ? to / ti : 0;
    add({ title: "First Tracked Major Exit", time: firstExitAt, tone: sellRatio >= 1 ? "danger" : "warning",
          body: `${shortAddress(firstMajorExit.wallet_address)} first observed sell was ${formatRelativeTime(firstExitAt, launchAt)} from ${originLabel}; observed sold ratio is about ${(sellRatio * 100).toFixed(1)}%.${reliability}` });
  }
  if (token.dex_id || token.pair_url) add({
    title: "DEX Listed / Visible", time: token.dexscreener_first_seen_at || token.pair_created_at || token.first_price_snapshot_at, tone: "pass",
    body: token.pair_url ? "Selected DexScreener pair is available." : `Detected on ${token.dex_id || "DEX"}.`,
  });
  if (hasDexAd) add({
    title: "DexScreener Promotion Observed",
    time: token.dex_promotion_first_seen_at || token.created_at,
    tone: Number(token.dex_active_boosts || 0) >= 500 ? "warning" : "pass",
    body: `${formatDexAdsText(token)}. Time is first stored observation, not necessarily exact purchase time.`,
  });
  add({ title: "Final Decision", time: token.created_at, tone: decisionTone(token.final_watchlist_status, token.final_watchlist_pass),
        body: `${token.final_watchlist_status || "PENDING"} - ${token.final_watchlist_reason || "No final reason stored."}` });

  const sorted = events.sort((l, r) => l.date.getTime() - r.date.getTime());
  document.querySelector("#tokenTimeline").innerHTML = sorted.map((e) => `
    <article class="timeline-item ${e.tone || ""}">
      <div class="timeline-card">
        <div class="timeline-head">
          <div class="timeline-title">${escapeHtml(e.title)}</div>
          <div class="timeline-time" title="${attr(formatDate(e.time))}">${escapeHtml(formatRelativeTime(e.time, launchAt))}</div>
        </div>
        <div class="timeline-body">${escapeHtml(e.body)}</div>
      </div>
    </article>
  `).join("");
}

function renderWallets(wallets) {
  const el = document.querySelector("#walletRows");
  if (!wallets.length) {
    el.innerHTML = `<tr><td class="empty" colspan="13">No wallet intelligence rows found yet.</td></tr>`;
    return;
  }
  el.innerHTML = wallets.map((wallet) => {
    const labels = parseJson(wallet.labels, []);
    const details = parseJson(wallet.details, {});
    const labelReasons = details.label_reasons || {};
    const reasons = labels.map((l) => labelReasons[l]).filter(Boolean);
    const fundingSource = wallet.funding_source || wallet.funder_address || "";
    return `
      <tr class="${walletRowClass(labels, wallet.wallet_score)}">
        <td>${escapeHtml(wallet.rank || "")}</td>
        <td>${walletCellHtml(wallet.wallet_address)}</td>
        <td>${formatPercent2dp(wallet.holder_percent)}</td>
        <td><div class="labels">
          ${labels.length ? labels.map((l) => `<span class="label ${labelClass(l)}">${escapeHtml(l)}</span>`).join("") : `<span class="label">UNKNOWN</span>`}
        </div></td>
        <td class="reason">${escapeHtml(reasons.join(" | ") || "N/A")}</td>
        <td>${scoreBadge(wallet.wallet_score)}</td>
        <td>${formatDate(wallet.first_entry_at)}</td>
        <td>${formatDuration(wallet.seconds_from_launch)}</td>
        <td>${formatNumber(wallet.total_token_in, 2)}</td>
        <td>${formatNumber(wallet.total_token_out, 2)}</td>
        <td>${formatNumber(wallet.net_token_amount, 2)}</td>
        <td>${escapeHtml(wallet.transaction_count ?? 0)}</td>
        <td>${walletCellHtml(fundingSource)}</td>
      </tr>`;
  }).join("");
}

function renderEarlyBuyers(wallets) {
  const buyers = wallets.filter((w) => w.first_entry_at)
    .sort((l, r) => new Date(l.first_entry_at) - new Date(r.first_entry_at)).slice(0, 20);
  const counts = buyers.reduce((acc, w) => {
    const d = parseJson(w.details, {});
    const eb = d.early_buyer || {};
    const status = String(eb.status || "UNKNOWN");
    const ps = String(eb.profit_state || "UNKNOWN");
    if (["HOLDING","PARTIAL_EXIT"].includes(status)) acc.holding += 1;
    if (["EXITED","MOSTLY_EXITED"].includes(status)) acc.exited += 1;
    if (ps === "PROFIT")     acc.profitable += 1;
    if (ps === "LOSS")       acc.loss += 1;
    if (ps === "UNREALIZED") acc.unrealized += 1;
    return acc;
  }, { holding: 0, exited: 0, profitable: 0, loss: 0, unrealized: 0 });

  document.querySelector("#earlyBuyerSummary").innerHTML = [
    ["Early buyers", buyers.length],
    ["Still holding", counts.holding],
    ["Exited", counts.exited],
    ["Profitable", counts.profitable],
  ].map(([label, value]) => `
    <article class="profit-stat">
      <span class="profit-stat-label">${escapeHtml(label)}</span>
      <span class="profit-stat-value">${escapeHtml(value)}</span>
    </article>
  `).join("");

  const tbody = document.querySelector("#earlyBuyerRows");
  if (!buyers.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="13">No early buyer rows found yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = buyers.map((wallet, index) => {
    const labels = parseJson(wallet.labels, []);
    const details = parseJson(wallet.details, {});
    const eb = details.early_buyer || {};
    const rowClass = eb.profit_state === "LOSS"
      ? "suspicious-row"
      : ["EXITED","MOSTLY_EXITED"].includes(eb.status) ? "warning-row" : "";
    return `
      <tr class="${rowClass}">
        <td>${index + 1}</td>
        <td>${walletCellHtml(wallet.wallet_address)}</td>
        <td>${formatDate(wallet.first_entry_at)}</td>
        <td>${formatDuration(wallet.seconds_from_launch)}</td>
        <td>${escapeHtml(eb.status || "UNKNOWN")}</td>
        <td>${profitStateBadge(eb.profit_state)}</td>
        <td>${formatNumber(wallet.total_token_in, 2)}</td>
        <td>${formatNumber(wallet.total_token_out, 2)}</td>
        <td>${formatNumber(wallet.net_token_amount, 2)}</td>
        <td>${formatSol(eb.native_spent)}</td>
        <td>${formatSol(eb.native_received)}</td>
        <td title="${attr(eb.pnl_note || "")}">${formatSol(eb.realized_pnl_native)}</td>
        <td><div class="labels">
          ${labels.length ? labels.map((l) => `<span class="label ${labelClass(l)}">${escapeHtml(l)}</span>`).join("") : `<span class="label">UNKNOWN</span>`}
        </div></td>
      </tr>`;
  }).join("");
}

function renderHolders(holders) {
  const el = document.querySelector("#holderRows");
  if (!holders.length) {
    el.innerHTML = `<tr><td class="empty" colspan="5">No top holders found yet.</td></tr>`;
    return;
  }
  el.innerHTML = holders.map((h) => `
    <tr>
      <td>${escapeHtml(h.rank || "")}</td>
      <td>${walletCellHtml(h.owner_address)}</td>
      <td>${formatNumber(h.amount, 2)}</td>
      <td>${formatPercent2dp(h.percent)}</td>
      <td>${escapeHtml(h.source || "N/A")}</td>
    </tr>`).join("");
}

function renderRelationships(rels) {
  const el = document.querySelector("#relationshipRows");
  if (!rels.length) {
    el.innerHTML = `<tr><td class="empty" colspan="6">No wallet relationship edges found yet.</td></tr>`;
    return;
  }
  el.innerHTML = rels.map((edge) => `
    <tr class="${relationshipClass(edge.relation_type) ? "suspicious-row" : ""}">
      <td><span class="relationship-type ${relationshipClass(edge.relation_type)}">${escapeHtml(edge.relation_type || "N/A")}</span></td>
      <td>${walletCellHtml(edge.from_wallet)}</td>
      <td>${walletCellHtml(edge.to_wallet)}</td>
      <td>${formatNumber(edge.amount, 2)}</td>
      <td>${formatDate(edge.timestamp)}</td>
      <td><div class="wallet-address" title="${attr(edge.signature || "")}">${escapeHtml(edge.signature || "N/A")}</div></td>
    </tr>`).join("");
}

// ---- Refresh Analysis flow ----------------------------------------

function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitForRefreshToFinish() {
  const statusEl = document.querySelector("#status");
  for (let i = 0; i < 180; i += 1) {
    const r = await fetch("/api/scan/status");
    if (!r.ok) throw new Error("Could not read scan status");
    const state = await r.json();
    if (statusEl) statusEl.textContent = `${state.status || "running"}: ${state.message || state.stage || ""}`;
    if (state.status === "failed") throw new Error(state.message || "Refresh analysis failed");
    if (!state.running && state.status === "finished") return state;
    await wait(2000);
  }
  throw new Error("Refresh analysis is still running");
}

async function findLatestTokenRow(tokenAddress) {
  const r = await fetch("/api/watchlist?limit=100");
  if (!r.ok) throw new Error("Could not load latest watchlist rows");
  const rows = await r.json();
  return rows.find((row) => row.token_address === tokenAddress) || null;
}

async function refreshCurrentToken(button) {
  if (!currentToken || !currentToken.token_address) return;
  const tokenAddress = currentToken.token_address;
  const statusEl = document.querySelector("#status");
  localStorage.setItem(snapshotKey(tokenAddress), JSON.stringify(tokenSnapshot(currentToken)));
  button.disabled = true;
  button.textContent = "Refreshing...";
  if (statusEl) statusEl.textContent = "Refresh analysis queued";
  try {
    const r = await fetch("/api/analyze-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token_address: tokenAddress }),
    });
    const state = await r.json();
    if (!r.ok && r.status !== 409) throw new Error(state.error || state.message || "Could not start refresh");
    await waitForRefreshToFinish();
    const latest = await findLatestTokenRow(tokenAddress);
    if (latest && latest.run_id && latest.token_id) {
      window.location.href = `/token?run_id=${encodeURIComponent(latest.run_id)}&token_id=${encodeURIComponent(latest.token_id)}`;
      return;
    }
    await loadDetail();
  } catch (error) {
    button.disabled = false;
    button.textContent = "Refresh Analysis";
    if (statusEl) statusEl.textContent = error.message || "Refresh failed";
  }
}

// ---- Bootstrap -----------------------------------------------------

async function loadDetail() {
  const query = params();
  const runId = query.get("run_id");
  const tokenId = query.get("token_id");
  const statusEl = document.querySelector("#status");

  if (!runId || !tokenId) {
    if (statusEl) statusEl.textContent = "Missing token identifiers";
    return;
  }
  try {
    const r = await fetch(`/api/token-detail?run_id=${encodeURIComponent(runId)}&token_id=${encodeURIComponent(tokenId)}`);
    if (!r.ok) throw new Error("Request failed");
    const data = await r.json();
    if (!data.token) {
      if (statusEl) statusEl.textContent = "Token not found";
      return;
    }
    currentToken = data.token;
    if (statusEl) statusEl.textContent = `Run #${runId}`;
    renderToken(data.token);
    renderChangeSignals(data.token);
    renderTokenTimeline(data.token, data.wallets || []);
    renderDecisionTree(data.token);
    renderWallets(data.wallets || []);
    renderEarlyBuyers(data.wallets || []);
    renderHolders(data.holders || []);
    renderRelationships(data.relationships || []);
  } catch {
    if (statusEl) statusEl.textContent = "Failed to load token details";
    document.querySelector("#walletRows").innerHTML = `<tr><td class="empty" colspan="13">Token detail request failed.</td></tr>`;
    document.querySelector("#earlyBuyerRows").innerHTML = `<tr><td class="empty" colspan="13">Token detail request failed.</td></tr>`;
    document.querySelector("#holderRows").innerHTML = `<tr><td class="empty" colspan="5">Token detail request failed.</td></tr>`;
    document.querySelector("#relationshipRows").innerHTML = `<tr><td class="empty" colspan="6">Token detail request failed.</td></tr>`;
  }
}

mount(appEl, renderShell("Loading..."));

document.addEventListener("click", (event) => {
  const refreshBtn = event.target.closest("#refreshTokenButton");
  if (refreshBtn) { refreshCurrentToken(refreshBtn); return; }
  const btn = event.target.closest(".copy-button");
  if (!btn) return;
  copyAddress(btn.dataset.address || "", btn);
});

loadDetail();
