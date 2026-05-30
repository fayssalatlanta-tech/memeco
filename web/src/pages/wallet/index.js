/**
 * Memeco — WALLET DOSSIER (Vite-built version).
 *
 * Same data and visual identity as app/static/wallet_detail.html.
 * Renders the tier emblem, identity hero, KPI HUD, P&L spark, ROI
 * balance scale, safety panel, and the Trades / Live Signals /
 * Holdings tabbed table.
 */

import "../../styles/tokens.css";
import "../../styles/cyberpunk.css";
import "./wallet.css";

import { api } from "../../lib/api.js";
import { formatDate } from "../../lib/time.js";
import { h, raw, mount, escapeHtml } from "../../lib/dom.js";
import {
  numberOrNull, formatNumber, formatMoney, formatSol, formatSignedPercent,
  shortAddress,
} from "../../lib/format.js";

import { BrandBar } from "../../components/BrandBar.js";
import {
  tierForPnl, tierMetaText, tierEmblemSvg,
} from "../../components/TierEmblem.js";

// ---- Page state -----------------------------------------------------
const params = new URLSearchParams(location.search);
const wallet = params.get("wallet") || params.get("address") || "";
const appEl = document.querySelector("#app");

let state = { trades: [], signals: [], wallet: null, stats: {} };
let activeTab = "trades";

// Aliases keeping the readable formatter names used throughout.
const num = numberOrNull;
const fmt = formatNumber;
const sol = formatSol;
const pct = formatSignedPercent;
const usd = formatMoney;

// ---- Helpers --------------------------------------------------------

function tokenLogoHtml(row) {
  const symbol = String(row.token_symbol || row.token_name || "?").slice(0, 2).toUpperCase();
  if (!row.logo_url) {
    return `<span class="token-logo token-fallback">${escapeHtml(symbol)}</span>`;
  }
  return `<img class="token-logo" src="${escapeHtml(row.logo_url)}" alt="" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'), { className: 'token-logo token-fallback', textContent: '${escapeHtml(symbol)}' }))">`;
}

function copyButtonHtml(value) {
  if (!value) return "";
  return `<button class="copy-btn" type="button" data-copy="${escapeHtml(value)}">C</button>`;
}

async function copyText(value, button) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  if (button) {
    const original = button.textContent;
    button.classList.add("copied");
    button.textContent = "OK";
    setTimeout(() => {
      button.classList.remove("copied");
      button.textContent = original;
    }, 900);
  }
}

function bucketPercent(count, total) {
  if (!total) return "0%";
  return `${fmt((count / total) * 100, 2)}%`;
}

function distributionHtml(rows) {
  return rows.map((r) => h`
    <div class="dist-row">
      <span><span class="dot ${raw(r.dot || "")}"></span>${r.label}</span>
      <strong class="${raw(r.className || "")}">${r.count} (${r.percent})</strong>
    </div>
  `).join("");
}

function pnlSparkHtml(values) {
  if (!values || !values.length) {
    return `<div class="wd-spark-empty">No trade history yet.</div>`;
  }
  const max = Math.max(0.0001, ...values.map((v) => Math.abs(Number(v) || 0)));
  return values.map((value) => {
    const v = Number(value);
    if (!Number.isFinite(v) || v === 0) {
      return `<span class="wd-spark-bar zero" title="0"></span>`;
    }
    const ratio = Math.min(100, (Math.abs(v) / max) * 100);
    const tone = v > 0 ? "good" : "bad";
    return `<span class="wd-spark-bar ${tone}" style="--h:${ratio}%" title="${escapeHtml(sol(v))}"></span>`;
  }).join("");
}

// ---- Render skeletons ----------------------------------------------

function brandBarHtml(walletAddress) {
  const wAddr = walletAddress || "";
  const right = `
    <button class="wd-icon-btn" id="copyWallet" type="button" title="Copy wallet address" data-copy="${escapeHtml(wAddr)}">⧉</button>
    <a class="wd-icon-btn" id="solscanLink" target="_blank" rel="noopener noreferrer" title="Open on Solscan"
       href="https://solscan.io/account/${encodeURIComponent(wAddr)}">↗</a>
    <a class="wd-icon-btn" id="trackLink" title="Filter Whale Radar to this wallet"
       href="/whale-radar?wallet=${encodeURIComponent(wAddr)}">⌖</a>
    <button class="wd-icon-btn" id="shareButton" type="button" title="Share">⌥</button>
  `;
  return BrandBar({
    name: "WALLET DOSSIER",
    tag: "SMART MONEY · IDENTITY",
    extraActive: "WALLET",
    right,
  });
}

function heroHtml({ walletData, totalPnl, pnlPct, unrealized, totalTrades, tier }) {
  const totalPnlCls = totalPnl >= 0 ? "good" : "bad";
  const unrealizedCls = unrealized >= 0 ? "good" : "bad";
  const pctCls = (pnlPct || 0) < 0 ? "loss" : "";
  const handle = shortAddress(walletData.wallet_address);
  return h`
    <section class="wd-hero" data-tier="${tier}">
      <div class="wd-emblem-stage">
        <div class="wd-emblem" id="tierEmblem" aria-hidden="true">${raw(tierEmblemSvg(tier))}</div>
        <div class="wd-tier-label">
          <div class="wd-tier-eyebrow">TIER</div>
          <div class="wd-tier-name">${tier}</div>
          <div class="wd-tier-meta">${tierMetaText(tier)}</div>
        </div>
      </div>
      <div class="wd-identity">
        <div class="wd-handle">
          <h1>${handle}</h1>
          <span class="wd-pill">SEEN ${formatDate(walletData.first_discovered_at)}</span>
        </div>
        <div class="wd-address-line"><code>${walletData.wallet_address || "N/A"}</code></div>
        <div class="wd-headline">
          <div class="wd-pnl-block">
            <div class="wd-pnl-label">TOTAL PnL</div>
            <div class="wd-pnl-big ${raw(totalPnlCls)}">${sol(totalPnl)}</div>
            <div class="wd-pnl-sub">
              <span class="${raw(pctCls)}">${pct(pnlPct)}</span> ROI ·
              <span class="${raw(unrealizedCls)}">${sol(unrealized)}</span> UNREALIZED
            </div>
          </div>
          <div class="wd-pnl-block">
            <div class="wd-pnl-label">WIN RATE</div>
            <div class="wd-pnl-big alt">${fmt(walletData.win_rate_percent, 2)}%</div>
            <div class="wd-pnl-sub">
              ${walletData.profitable_trade_count || 0}/${totalTrades} PROFITABLE ·
              ${fmt(walletData.reliability_score_10, 2)}/10 RELIABILITY
            </div>
          </div>
        </div>
        <a class="wd-cta" href="/whale-radar?wallet=${encodeURIComponent(walletData.wallet_address || "")}">► OPEN ON WHALE RADAR</a>
      </div>
    </section>
  `;
}

function hudHtml({ walletData, stats, totalTrades }) {
  const securityCls = walletData.security_level === "SAFE_TO_WATCH" ? "good" : "warn";
  return h`
    <section class="cy-hud">
      <div><div class="lbl">TRADES</div>      <div class="val">${totalTrades || "—"}</div></div>
      <div><div class="lbl">AVG HOLD</div>    <div class="val">${walletData.avg_hold_minutes ? `${fmt(walletData.avg_hold_minutes, 1)}m` : "—"}</div></div>
      <div><div class="lbl">TOTAL COST</div>  <div class="val">${sol(stats.total_spent_sol)}</div></div>
      <div><div class="lbl">RECEIVED / SPENT</div><div class="val">${sol(stats.total_received_sol)} / ${sol(stats.total_spent_sol)}</div></div>
      <div><div class="lbl">AVG ROI</div>     <div class="val">${pct(stats.avg_roi_percent)}</div></div>
      <div><div class="lbl">AVG ENTRY</div>   <div class="val">${stats.avg_minutes_after_launch ? `${fmt(stats.avg_minutes_after_launch, 1)}m` : "—"}</div></div>
      <div><div class="lbl">STYLE</div>       <div class="val">${walletData.whale_style || "—"}</div></div>
      <div><div class="lbl">SECURITY</div>    <div class="val ${raw(securityCls)}">${walletData.security_level || "—"}</div></div>
    </section>
  `;
}

function analyticsHtml({ walletData, stats, totalTrades, pnlValues, winCount, lossCount, distSplits, roiRows, buyRows }) {
  const tilt = (() => {
    const total = (winCount + lossCount) || 1;
    const w = (winCount / total) * 100;
    const l = (lossCount / total) * 100;
    return Math.max(-6, Math.min(6, ((w - l) / 100) * 6));
  })();
  const winsHeight = Math.max(8, ((winCount  / ((winCount + lossCount) || 1)) * 100));
  const lossHeight = Math.max(8, ((lossCount / ((winCount + lossCount) || 1)) * 100));
  return raw(`
    <section class="wd-analytics">
      <article class="cy-panel wd-spark">
        <header class="cy-section-head">
          <h2>RECENT P&amp;L SPARK</h2>
          <div class="cy-section-note">Last 25 closed/tracked trades, oldest left → newest right</div>
        </header>
        <div class="wd-spark-stage">
          <div class="wd-spark-axis"><span>+</span><span>0</span><span>−</span></div>
          <div class="wd-spark-bars">${pnlSparkHtml(pnlValues)}</div>
        </div>
      </article>
      <article class="cy-panel wd-balance">
        <header class="cy-section-head">
          <h2>ROI BALANCE</h2>
          <div class="cy-section-note">Wins (left) versus losses (right)</div>
        </header>
        <div class="wd-balance-scale" style="--tilt:${tilt}deg">
          <div class="wd-balance-side wins"><div class="wd-balance-label">WINS</div><div class="wd-balance-fill" style="height:${winsHeight}%"></div></div>
          <div class="wd-balance-fulcrum" aria-hidden="true">▲</div>
          <div class="wd-balance-side losses"><div class="wd-balance-label">LOSSES</div><div class="wd-balance-fill" style="height:${lossHeight}%"></div></div>
        </div>
        <div class="wd-balance-bar">
          <span class="g1" style="width:${distSplits[0]}%"></span>
          <span class="g2" style="width:${distSplits[1]}%"></span>
          <span class="r1" style="width:${distSplits[2]}%"></span>
          <span class="r2" style="width:${distSplits[3]}%"></span>
        </div>
        <div class="wd-balance-list">${distributionHtml(roiRows)}</div>
      </article>
      <article class="cy-panel wd-safety">
        <header class="cy-section-head">
          <h2>SAFETY</h2>
          <div class="cy-section-note">Phishing / exposure / behavior checks</div>
        </header>
        <div class="wd-safety-grid">
          <div class="wd-safety-row"><span><span class="dot"></span>Blacklist</span>     <strong>${escapeHtml(walletData.security_level === "INSIDER_RISK" ? "Warning" : "0")}</strong></div>
          <div class="wd-safety-row"><span><span class="dot"></span>Sold &gt; Bought</span> <strong>${num(stats.total_received_sol) > num(stats.total_spent_sol) ? "Yes" : "No"}</strong></div>
          <div class="wd-safety-row"><span><span class="dot red"></span>Rug exposure</span><strong>${escapeHtml(walletData.rugged_trade_count || 0)} rugs</strong></div>
          <div class="wd-safety-row"><span><span class="dot red"></span>Bot flag</span>   <strong>${walletData.bot_flag ? "Yes" : "No"}</strong></div>
        </div>
        <header class="cy-section-head" style="margin-top:14px;">
          <h2>BUY SIZE</h2>
          <div class="cy-section-note">Distribution of trade sizes</div>
        </header>
        <div class="wd-balance-list">${distributionHtml(buyRows)}</div>
      </article>
    </section>
  `).value;
}

function tabsHtml() {
  return `
    <section class="cy-panel wd-tableblock">
      <header class="wd-tabs">
        <button class="wd-tab ${activeTab === "trades"   ? "is-active" : ""}" data-tab="trades"   type="button">TRADES</button>
        <button class="wd-tab ${activeTab === "signals"  ? "is-active" : ""}" data-tab="signals"  type="button">LIVE SIGNALS</button>
        <button class="wd-tab ${activeTab === "holdings" ? "is-active" : ""}" data-tab="holdings" type="button">HOLDINGS</button>
      </header>
      <div class="table-wrap">
        <table>
          <thead id="tableHead"></thead>
          <tbody id="tableBody"></tbody>
        </table>
      </div>
    </section>
  `;
}

// ---- Tables --------------------------------------------------------

function renderTrades() {
  document.querySelector("#tableHead").innerHTML = `
    <tr>
      <th>Type</th><th>Token</th><th>MC</th><th>Spent</th><th>Received</th>
      <th>PnL</th><th>ROI</th><th>Age</th><th>Status</th><th>Decision</th>
    </tr>`;
  document.querySelector("#tableBody").innerHTML = state.trades.length ? state.trades.map((trade) => {
    const pnl = num(trade.pnl_sol) ?? num(trade.current_unrealized_pnl_sol) ?? 0;
    const symbol = trade.token_symbol || trade.token_name || shortAddress(trade.token_address || "");
    const decisionClass = trade.final_watchlist_pass
      ? "good"
      : (String(trade.final_watchlist_status || "").includes("REJECT") ? "bad" : "warn");
    return `
      <tr>
        <td><span class="badge ${pnl >= 0 ? "good" : "bad"}">${pnl >= 0 ? "WIN" : "LOSS"}</span></td>
        <td><div class="token-cell">${tokenLogoHtml(trade)}<span>${escapeHtml(symbol)}</span>${copyButtonHtml(trade.token_address)}</div></td>
        <td>${escapeHtml(usd(trade.market_cap_usd || trade.fdv_usd))}</td>
        <td>${escapeHtml(sol(trade.native_spent_sol))}</td>
        <td>${escapeHtml(sol(trade.native_received_sol))}</td>
        <td class="${pnl >= 0 ? "good" : "bad"}">${escapeHtml(sol(pnl))}</td>
        <td class="${(num(trade.roi_percent) || 0) >= 0 ? "good" : "bad"}">${escapeHtml(pct(trade.roi_percent))}</td>
        <td>${escapeHtml(trade.minutes_after_launch ? `${fmt(trade.minutes_after_launch, 1)}m` : "N/A")}</td>
        <td>${escapeHtml(trade.trade_status || "OBSERVED")}</td>
        <td><span class="badge ${decisionClass}">${escapeHtml(trade.final_watchlist_status || "N/A")}</span></td>
      </tr>`;
  }).join("") : `<tr><td class="empty" colspan="10">No trades for this wallet yet.</td></tr>`;
}

function renderSignals() {
  document.querySelector("#tableHead").innerHTML = `
    <tr><th>Signal</th><th>Token</th><th>Amount</th><th>Source</th><th>Time</th><th>Signature</th></tr>`;
  document.querySelector("#tableBody").innerHTML = state.signals.length ? state.signals.map((signal) => {
    const symbol = signal.token_symbol || signal.token_name || shortAddress(signal.token_address || "");
    return `
      <tr>
        <td><span class="badge ${signal.signal_type === "SELL" ? "bad" : "good"}">${escapeHtml(signal.signal_type)}</span></td>
        <td><div class="token-cell">${tokenLogoHtml(signal)}<span>${escapeHtml(symbol)}</span>${copyButtonHtml(signal.token_address)}</div></td>
        <td>${escapeHtml(sol(signal.amount_sol))}</td>
        <td>${escapeHtml(signal.source || "N/A")}</td>
        <td>${escapeHtml(formatDate(signal.signal_at))}</td>
        <td>${signal.signature ? `<a href="https://solscan.io/tx/${escapeHtml(signal.signature)}" target="_blank" rel="noopener noreferrer">Solscan</a>` : "N/A"}</td>
      </tr>`;
  }).join("") : `<tr><td class="empty" colspan="6">No live signals for this wallet yet.</td></tr>`;
}

function renderHoldings() {
  const open = state.trades.filter((trade) => !trade.exit_at && (num(trade.current_value_sol) || 0) > 0);
  document.querySelector("#tableHead").innerHTML = `
    <tr><th>Token</th><th>Current Value</th><th>Unrealized PnL</th><th>Price Native</th><th>Liquidity</th><th>Updated</th></tr>`;
  document.querySelector("#tableBody").innerHTML = open.length ? open.map((trade) => {
    const pnl = num(trade.current_unrealized_pnl_sol) ?? 0;
    const symbol = trade.token_symbol || trade.token_name || shortAddress(trade.token_address || "");
    return `
      <tr>
        <td><div class="token-cell">${tokenLogoHtml(trade)}<span>${escapeHtml(symbol)}</span>${copyButtonHtml(trade.token_address)}</div></td>
        <td>${escapeHtml(sol(trade.current_value_sol))}</td>
        <td class="${pnl >= 0 ? "good" : "bad"}">${escapeHtml(sol(pnl))}</td>
        <td>${escapeHtml(fmt(trade.current_price_native, 8))}</td>
        <td>${escapeHtml(usd(trade.liquidity_usd))}</td>
        <td>${escapeHtml(formatDate(trade.price_refreshed_at))}</td>
      </tr>`;
  }).join("") : `<tr><td class="empty" colspan="6">No open tracked holdings found.</td></tr>`;
}

function renderTable() {
  if (activeTab === "signals")        renderSignals();
  else if (activeTab === "holdings")  renderHoldings();
  else                                renderTrades();
}

// ---- Page bootstrap -------------------------------------------------

function buildPage() {
  const walletData = state.wallet || {};
  const stats = state.stats || {};
  const totalTrades = Number(stats.trade_count || walletData.trade_count || 0);
  const totalPnl = num(stats.total_pnl_sol) ?? num(walletData.total_profit_sol) ?? 0;
  const totalSpent = num(stats.total_spent_sol) ?? 0;
  const pnlPct = totalSpent > 0 ? (totalPnl / totalSpent) * 100 : num(walletData.avg_roi_percent);
  const unrealized = num(stats.unrealized_pnl_sol) ?? 0;
  const tier = tierForPnl(totalPnl);

  const roiRows = [
    { label: ">500%",       count: stats.roi_over_500     || 0, dot: "",    className: "good" },
    { label: "200% - 500%", count: stats.roi_200_500      || 0, dot: "",    className: "good" },
    { label: "0% - 200%",   count: stats.roi_0_200        || 0, dot: "",    className: "good" },
    { label: "-50% - 0%",   count: stats.roi_neg_50_0     || 0, dot: "red", className: "bad" },
    { label: "<-50%",       count: stats.roi_below_neg_50 || 0, dot: "red", className: "bad" },
  ].map((r) => ({ ...r, percent: bucketPercent(Number(r.count), totalTrades) }));

  const counts = roiRows.map((r) => Number(r.count));
  const sumCounts = counts.reduce((a, b) => a + b, 0) || 1;
  const distSplits = [
    (counts[0] / sumCounts) * 100,
    ((counts[1] + counts[2]) / sumCounts) * 100,
    (counts[3] / sumCounts) * 100,
    (counts[4] / sumCounts) * 100,
  ];
  const winCount  = counts[0] + counts[1] + counts[2];
  const lossCount = counts[3] + counts[4];

  const buyRows = [
    { label: "<1 SOL",  count: stats.buy_small  || 0 },
    { label: "1-5 SOL", count: stats.buy_medium || 0 },
    { label: ">5 SOL",  count: stats.buy_large  || 0 },
  ].map((r) => ({ ...r, percent: bucketPercent(Number(r.count), totalTrades) }));

  const pnlValues = state.trades.slice(0, 25)
    .map((trade) => num(trade.pnl_sol) ?? num(trade.current_unrealized_pnl_sol))
    .reverse();

  return [
    brandBarHtml(walletData.wallet_address),
    heroHtml({ walletData, totalPnl, pnlPct, unrealized, totalTrades, tier }),
    hudHtml({ walletData, stats, totalTrades }),
    analyticsHtml({
      walletData, stats, totalTrades,
      pnlValues, winCount, lossCount, distSplits, roiRows, buyRows,
    }),
    tabsHtml(),
  ].join("");
}

function attachListeners() {
  appEl.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-copy]");
    if (btn) {
      copyText(btn.dataset.copy, btn);
      return;
    }
    const shareBtn = event.target.closest("#shareButton");
    if (shareBtn) {
      copyText(location.href, shareBtn);
      return;
    }
    const tab = event.target.closest(".wd-tab");
    if (tab) {
      activeTab = tab.dataset.tab;
      document.querySelectorAll(".wd-tab").forEach((t) => t.classList.toggle("is-active", t === tab));
      renderTable();
    }
  });
}

function showError(message) {
  mount(appEl, [
    brandBarHtml(""),
    h`
      <section class="cy-panel">
        <header class="cy-section-head"><h2>WALLET</h2></header>
        <div class="cy-error">
          <div class="meta">FETCH</div>
          <div class="msg">${message}</div>
        </div>
      </section>
    `,
  ].join(""));
}

async function loadWallet() {
  if (!wallet) {
    showError("Missing wallet address (use ?wallet=...)");
    return;
  }
  try {
    const data = await api.walletDetail(wallet);
    if (!data.wallet) throw new Error("Wallet not found in Whale Radar");
    state = data;
    mount(appEl, buildPage());
    attachListeners();
    renderTable();
  } catch (error) {
    showError(error.message);
  }
}

loadWallet();
