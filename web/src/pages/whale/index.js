/**
 * Memeco — WHALE RADAR / RADAR CONSOLE (Vite-built version).
 *
 * Same data and visual identity as app/static/whale_radar.html.
 * Renders the radar orb (with sweeping arm + pulsing pip flashing on
 * new signals), the vertical command rail, KPI HUD, alerts grid
 * (incoming high-signal + group-buy confluence), elite leaderboard
 * with rank chips, live feed, and the auto-analysis queue.
 */

import "../../styles/tokens.css";
import "../../styles/cyberpunk.css";
import "./whale.css";

import { mount, escapeHtml } from "../../lib/dom.js";
import { numberOrNull, formatNumber, shortAddress, shortWallet } from "../../lib/format.js";
import { timeAgo } from "../../lib/time.js";

import { BrandBar } from "../../components/BrandBar.js";

const appEl = document.querySelector("#app");
let selectedWallet = null;
let radarLastId = null;

// ---- Page-local formatters ---------------------------------------

function money(value, suffix = "") {
  const n = numberOrNull(value);
  if (n === null) return "N/A";
  return `${formatNumber(n, n >= 10 ? 2 : 4)}${suffix}`;
}
function percent(value) {
  const n = numberOrNull(value);
  if (n === null) return "N/A";
  return `${formatNumber(n, 2)}%`;
}
function initials(address) {
  if (!address) return "NA";
  return `${address.slice(0, 2)}${address.slice(-2)}`.toUpperCase();
}
function timeText(value) {
  if (!value) return "N/A";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "N/A";
  return d.toLocaleString();
}

// ---- Class helpers ------------------------------------------------

function badgeClass(label, botFlag) {
  if (botFlag) return "bot";
  if (label === "ELITE_SMART_MONEY") return "elite";
  if (label === "WATCHLIST_CANDIDATE") return "watch";
  return "";
}
function securityClass(level) {
  if (level === "SAFE_TO_WATCH") return "elite";
  if (level === "RISKY" || level === "INSIDER_RISK") return "bot";
  return "watch";
}
function signalTypeClass(type) {
  const t = String(type || "").toUpperCase();
  if (t === "BUY") return "buy";
  if (t === "SELL") return "sell";
  if (t === "TOKEN_IN")  return "token-in";
  if (t === "TOKEN_OUT") return "token-out";
  return "wait";
}
function jobStatusClass(status) {
  const t = String(status || "").toLowerCase();
  if (t === "finished") return "finished";
  if (t === "failed")   return "failed";
  if (t === "running")  return "running";
  return "queued";
}
function jsonList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch { return []; }
}
function scoreWidth(value) {
  const score = numberOrNull(value) ?? 0;
  return Math.max(0, Math.min(100, score));
}

function copyButton(value, label = "Copy address") {
  if (!value) return "";
  return `<button class="copy-btn" type="button" data-copy="${escapeHtml(value)}" title="${escapeHtml(label)}">⧉</button>`;
}
function solscanWalletLink(addr) {
  if (!addr) return "";
  return `<a class="external-link" href="https://solscan.io/account/${escapeHtml(addr)}" target="_blank" rel="noopener noreferrer" title="Open wallet on Solscan">↗</a>`;
}
function walletDetailLink(addr) {
  if (!addr) return "";
  return `<a class="external-link" href="/wallet?wallet=${encodeURIComponent(addr)}" title="Open wallet detail">W</a>`;
}
function tokenDetailLink(signal) {
  if (!signal.decision_run_id || !signal.decision_token_id) return "";
  const url = `/token?run_id=${encodeURIComponent(signal.decision_run_id)}&token_id=${encodeURIComponent(signal.decision_token_id)}`;
  return `<a class="external-link" href="${url}" title="Open token detail">T</a>`;
}
function tokenLogo(signal) {
  const symbol = String(signal.token_symbol || signal.token_name || "?").slice(0, 2).toUpperCase();
  if (!signal.logo_url) return `<span class="token-logo token-fallback">${escapeHtml(symbol)}</span>`;
  return `<img class="token-logo" src="${escapeHtml(signal.logo_url)}" alt="" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'), { className: 'token-logo token-fallback', textContent: '${escapeHtml(symbol)}' }))">`;
}
function tokenLogoFromFields(symbolValue, nameValue, logoUrl) {
  const symbol = String(symbolValue || nameValue || "?").slice(0, 2).toUpperCase();
  if (!logoUrl) return `<span class="token-logo token-fallback">${escapeHtml(symbol)}</span>`;
  return `<img class="token-logo" src="${escapeHtml(logoUrl)}" alt="" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'), { className: 'token-logo token-fallback', textContent: '${escapeHtml(symbol)}' }))">`;
}

async function copyText(value, button) {
  if (!value) return;
  try { await navigator.clipboard.writeText(value); }
  catch {
    const ta = document.createElement("textarea");
    ta.value = value; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  if (button) {
    button.classList.add("copied");
    button.textContent = "✓";
    setTimeout(() => { button.classList.remove("copied"); button.textContent = "⧉"; }, 900);
  }
}

function signalQuality(signal) {
  const type = String(signal.signal_type || "").toUpperCase();
  const amount = numberOrNull(signal.amount_sol) ?? 0;
  const score10 = numberOrNull(signal.reliability_score_10) ?? ((numberOrNull(signal.reliability_score) ?? 0) / 10);
  const security = String(signal.security_level || "UNPROVEN");
  if (!["BUY","TOKEN_IN"].includes(type))                   return { label: "ACTIVITY",            className: "wait",   reason: "Not a buy signal" };
  if (amount > 0 && amount < 0.1)                            return { label: "LOW_VALUE_NOISE",     className: "noise",  reason: "Small value movement" };
  if (security === "SAFE_TO_WATCH" && score10 >= 5 && amount >= 0.5)
                                                             return { label: "WHALE_ENTRY",         className: "strong", reason: "Safe wallet with meaningful size" };
  if (score10 >= 5)                                          return { label: "SMART_WALLET_ENTRY",  className: "strong", reason: "Reliable tracked wallet" };
  return { label: "WATCH", className: "wait", reason: "Needs review" };
}
function decisionBadge(signal) {
  if (!signal.final_watchlist_status) return `<span class="badge watch">NOT_ANALYZED</span>`;
  const status = String(signal.final_watchlist_status);
  const cls = signal.final_watchlist_pass ? "elite" : (status.includes("REJECT") ? "bot" : "watch");
  return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
}
function renderWalletMinis(addresses) {
  const wallets = Array.isArray(addresses) ? addresses.slice(0, 5) : [];
  return wallets.map((a) => `<span class="wallet-mini" title="${escapeHtml(a)}">${escapeHtml(shortWallet(a, 5, 5))}</span>`).join("");
}

// ---- Renderers ----------------------------------------------------

function updateRadarReadout(signal) {
  const lineEl = document.querySelector("#radarLastWallet");
  const metaEl = document.querySelector("#radarLastMeta");
  const pipEl  = document.querySelector("#radarPip");
  if (!signal) {
    if (lineEl) lineEl.textContent = "— · —";
    if (metaEl) metaEl.textContent = "No live signal yet";
    return;
  }
  const wallet = shortWallet(signal.wallet_address || "", 5, 5);
  const token = signal.token_symbol || signal.token_name || "—";
  const type = String(signal.signal_type || "SIGNAL").toUpperCase();
  const amount = signal.amount_sol ? `${money(signal.amount_sol)} SOL · ` : "";
  if (lineEl) lineEl.textContent = `${wallet} · ${token}`;
  if (metaEl) metaEl.textContent = `${type} · ${amount}${timeAgo(signal.signal_at)}`;
  const id = signal.id ?? signal.signal_at;
  if (id !== radarLastId) {
    radarLastId = id;
    if (pipEl) {
      pipEl.classList.remove("flash");
      void pipEl.offsetWidth; // force reflow so animation restarts
      pipEl.classList.add("flash");
    }
  }
}

function renderSummary(data) {
  const summary = data.summary || {};
  const shadow = data.shadow_performance || {};
  const avgScore = numberOrNull(summary.avg_reliability_score) ?? 0;
  const shadowWins = Number(shadow.winning_trade_count || 0);
  const shadowTrades = Number(shadow.tracked_trade_count || 0);
  const cards = [
    ["Elite",      summary.elite_count ?? 0,       "Approved smart-money wallets"],
    ["Tracked",    summary.wallet_count ?? 0,      "All wallets stored in radar"],
    ["Safe",       summary.safe_to_watch_count ?? 0,  "Passed survival/security checks"],
    ["Risky",      summary.risky_survival_count ?? 0, "Needs caution before copying"],
    ["Avg score",  `${money(avgScore / 10)}/10`,   "Reliability after scoring"],
    ["Shadow 24h", money(shadow.shadow_profit_sol, " SOL"), `${shadowWins}/${shadowTrades} profitable tracked trades`],
  ];
  document.querySelector("#summaryGrid").innerHTML = cards.map(([label, value, note]) => `
    <article class="metric">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value">${escapeHtml(value)}</div>
      <small>${escapeHtml(note)}</small>
    </article>
  `).join("");
}

function renderLeaderboard(rows) {
  const totalEl = document.querySelector("#leaderTotal");
  if (totalEl) totalEl.textContent = String(rows.length);
  const tbody = document.querySelector("#leaderboardRows");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="11">No elite wallets discovered yet. Run whale discovery after wallet intelligence has PnL data.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((row, i) => {
    const score100 = numberOrNull(row.reliability_score) ?? 0;
    const score10 = numberOrNull(row.reliability_score_10) ?? (score100 / 10);
    const favorites = jsonList(row.favorite_token_symbols).slice(0, 3).join(", ");
    return `
      <tr class="wallet-row ${selectedWallet === row.wallet_address ? "selected" : ""}" data-wallet="${escapeHtml(row.wallet_address)}">
        <td><span class="rank-chip" data-rank="${i + 1}">${i + 1}</span></td>
        <td>
          <div class="wallet-line">
            <div class="wallet-avatar">${escapeHtml(initials(row.wallet_address))}</div>
            <div>
              <div class="address-actions">
                <div class="wallet" title="${escapeHtml(row.wallet_address)}">${escapeHtml(shortWallet(row.wallet_address, 5, 5))}</div>
                ${copyButton(row.wallet_address, "Copy wallet address")}
                ${walletDetailLink(row.wallet_address)}
                ${solscanWalletLink(row.wallet_address)}
              </div>
              <div class="micro">
                <span class="badge ${badgeClass(row.label, row.bot_flag)}">${escapeHtml(row.label || "UNKNOWN")}</span>
              </div>
            </div>
          </div>
        </td>
        <td>
          <div class="score-box">
            <div class="score-main">${escapeHtml(money(score10))}/10</div>
            <div class="bar"><span style="width:${scoreWidth(score100)}%"></span></div>
            <div class="micro">${escapeHtml(money(score100))}/100</div>
          </div>
        </td>
        <td>
          <div class="money"><strong>${escapeHtml(money(row.total_profit_sol, " SOL"))}</strong></div>
          <div class="micro">30d ${escapeHtml(money(row.total_profit_30d_sol, " SOL"))}</div>
        </td>
        <td>${escapeHtml(percent(row.win_rate_percent))}</td>
        <td>
          <strong>${escapeHtml(row.trade_count ?? 0)}</strong>
          <div class="micro">Wins ${escapeHtml(row.profitable_trade_count ?? 0)}</div>
        </td>
        <td>${escapeHtml(percent(row.avg_roi_percent))}</td>
        <td>
          ${escapeHtml(row.avg_minutes_after_launch === null || row.avg_minutes_after_launch === undefined ? "N/A" : `${money(row.avg_minutes_after_launch)}m`)}
          <div class="micro">After launch</div>
        </td>
        <td>
          <div class="stack">
            <span class="badge ${securityClass(row.security_level)}">${escapeHtml(row.survival_rate_percent === null || row.survival_rate_percent === undefined ? "N/A" : percent(row.survival_rate_percent))}</span>
            <div class="micro">Rugs ${escapeHtml(row.rugged_trade_count ?? "N/A")} | Ladder ${escapeHtml(money(row.laddering_score))}</div>
          </div>
        </td>
        <td>
          <div class="stack-row">
            <span class="badge watch">${escapeHtml(row.whale_style || "UNKNOWN")}</span>
            <span class="badge">${escapeHtml(row.exit_style || "UNKNOWN")}</span>
          </div>
          <div class="micro">${escapeHtml(favorites ? `Likes ${favorites}` : "No favorite sector yet")}</div>
        </td>
        <td><span class="badge ${securityClass(row.security_level)}">${escapeHtml(row.security_level || "UNKNOWN")}</span></td>
      </tr>`;
  }).join("");
}

function renderFeed(signals) {
  const filterValueEl = document.querySelector("#feedFilterLabel b");
  if (filterValueEl) filterValueEl.textContent = selectedWallet ? shortWallet(selectedWallet, 5, 5) : "ALL WALLETS";
  const clearBtn = document.querySelector("#clearFeedFilter");
  if (clearBtn) clearBtn.style.display = selectedWallet ? "inline-flex" : "none";

  updateRadarReadout(signals[0] || null);

  const feedEl = document.querySelector("#liveFeed");
  if (!signals.length) {
    feedEl.innerHTML = selectedWallet
      ? `<div class="empty">No captured movements for this wallet in the current feed window.</div>`
      : `<div class="empty">No live whale signals yet. Sync webhook first, then Helius will push wallet events here.</div>`;
    return;
  }

  feedEl.innerHTML = signals.map((signal) => {
    const type = String(signal.signal_type || "SIGNAL").toUpperCase();
    const token = signal.token_symbol || signal.token_name || "Unknown token";
    const score10 = numberOrNull(signal.reliability_score_10) ?? ((numberOrNull(signal.reliability_score) ?? 0) / 10);
    const quality = signalQuality(signal);
    return `
      <article class="signal-card">
        <div class="signal-head">
          <div class="token-line">
            ${tokenLogo(signal)}
            <div>
              <span class="pill ${signalTypeClass(type)}">${escapeHtml(type)}</span>
              <span class="pill ${quality.className}">${escapeHtml(quality.label)}</span>
              <div class="signal-token">${escapeHtml(token)}</div>
              <div class="address-actions micro">
                <span title="${escapeHtml(signal.token_address)}">${escapeHtml(shortAddress(signal.token_address))}</span>
                ${copyButton(signal.token_address, "Copy token address")}
                ${tokenDetailLink(signal)}
              </div>
            </div>
          </div>
          <div class="micro">${escapeHtml(timeText(signal.signal_at))}</div>
        </div>
        <div class="signal-grid">
          <div class="signal-stat">
            <div class="label">Wallet</div>
            <div class="address-actions">
              <strong title="${escapeHtml(signal.wallet_address)}">${escapeHtml(shortWallet(signal.wallet_address, 5, 5))}</strong>
              ${copyButton(signal.wallet_address, "Copy wallet address")}
              ${walletDetailLink(signal.wallet_address)}
              ${solscanWalletLink(signal.wallet_address)}
            </div>
          </div>
          <div class="signal-stat"><div class="label">Amount</div><strong>${escapeHtml(money(signal.amount_sol, " SOL"))}</strong></div>
          <div class="signal-stat"><div class="label">Reliability</div><strong>${escapeHtml(money(score10))}/10</strong></div>
          <div class="signal-stat"><div class="label">Source</div><strong>${escapeHtml(signal.source || "webhook")}</strong></div>
          <div class="signal-stat"><div class="label">Decision</div><strong>${decisionBadge(signal)}</strong></div>
          <div class="signal-stat"><div class="label">Why</div><strong>${escapeHtml(quality.reason)}</strong></div>
        </div>
      </article>`;
  }).join("");
}

function renderHighSignalAlerts(alerts, settings) {
  const minSol = settings?.alert_min_amount_sol ?? 0.1;
  const minScore = settings?.alert_min_score_10 ?? 5;
  const sub = document.querySelector("#alertSubtitle");
  if (sub) sub.textContent = `Filtered BUY/TOKEN_IN events: min ${minSol} SOL, min ${minScore}/10 score, excluding SOL/USDC/USDT noise.`;
  const el = document.querySelector("#highSignalAlerts");
  if (!alerts.length) {
    el.innerHTML = `<div class="empty">No high signal alerts yet. The raw Live Feed may still contain small movements.</div>`;
    return;
  }
  el.innerHTML = alerts.map((signal) => {
    const token = signal.token_symbol || signal.token_name || "Unknown token";
    const score10 = numberOrNull(signal.reliability_score_10) ?? ((numberOrNull(signal.reliability_score) ?? 0) / 10);
    const quality = signalQuality(signal);
    const status = String(signal.final_watchlist_status || "");
    const cardClass = status.includes("REJECT") ? "danger" : (!status ? "review" : "");
    return `
      <article class="alert-card ${cardClass}">
        <div class="signal-head">
          <div class="token-line">
            ${tokenLogo(signal)}
            <div>
              <span class="pill ${quality.className}">${escapeHtml(quality.label)}</span>
              <div class="signal-token">${escapeHtml(token)}</div>
              <div class="address-actions micro">
                <span title="${escapeHtml(signal.token_address)}">${escapeHtml(shortAddress(signal.token_address))}</span>
                ${copyButton(signal.token_address, "Copy token address")}
                ${tokenDetailLink(signal)}
              </div>
            </div>
          </div>
        </div>
        <div class="stack">
          <div class="stack-row">
            <span class="badge strong">${escapeHtml(money(signal.amount_sol, " SOL"))}</span>
            <span class="badge">${escapeHtml(money(score10))}/10</span>
          </div>
          <div class="address-actions micro">
            <span title="${escapeHtml(signal.wallet_address)}">${escapeHtml(shortWallet(signal.wallet_address, 5, 5))}</span>
            ${copyButton(signal.wallet_address, "Copy wallet address")}
            ${walletDetailLink(signal.wallet_address)}
            ${solscanWalletLink(signal.wallet_address)}
          </div>
          ${decisionBadge(signal)}
          <div class="micro">${escapeHtml(timeText(signal.signal_at))}</div>
        </div>
      </article>`;
  }).join("");
}

function renderConfluenceAlerts(alerts, settings) {
  const minWallets = settings?.confluence_min_wallets ?? 2;
  const windowHours = settings?.confluence_window_hours ?? 24;
  const sub = document.querySelector("#confluenceSubtitle");
  if (sub) sub.textContent = `Shows tokens bought by at least ${minWallets} watched wallets within ${windowHours}h after noise filtering.`;
  const el = document.querySelector("#confluenceAlerts");
  if (!alerts.length) {
    el.innerHTML = `<div class="empty">No token confluence yet. This stays empty until multiple watched wallets enter the same non-noise token.</div>`;
    return;
  }
  el.innerHTML = alerts.map((alert) => {
    const token = alert.token_symbol || alert.token_name || "Unknown token";
    const detailSignal = {
      decision_run_id: alert.decision_run_id,
      decision_token_id: alert.decision_token_id,
      final_watchlist_status: alert.final_watchlist_status,
      final_watchlist_pass: alert.final_watchlist_pass,
    };
    return `
      <article class="confluence-card">
        <div class="signal-head">
          <div class="token-line">
            ${tokenLogoFromFields(alert.token_symbol, alert.token_name, alert.logo_url)}
            <div>
              <span class="pill token-in">MULTI_WALLET</span>
              <div class="signal-token">${escapeHtml(token)}</div>
              <div class="address-actions micro">
                <span title="${escapeHtml(alert.token_address)}">${escapeHtml(shortAddress(alert.token_address))}</span>
                ${copyButton(alert.token_address, "Copy token address")}
                ${tokenDetailLink(alert)}
              </div>
            </div>
          </div>
        </div>
        <div class="stack">
          <div class="stack-row">
            <span class="badge strong">${escapeHtml(alert.wallet_count)} wallets</span>
            <span class="badge">${escapeHtml(money(alert.total_amount_sol, " SOL"))}</span>
            <span class="badge">${escapeHtml(money(alert.avg_reliability_score_10))}/10 avg</span>
          </div>
          ${decisionBadge(detailSignal)}
          <div class="wallet-strip">${renderWalletMinis(alert.wallet_addresses)}</div>
          <div class="micro">Latest ${escapeHtml(timeText(alert.latest_signal_at))}</div>
        </div>
      </article>`;
  }).join("");
}

function renderSignalJobs(jobs) {
  const el = document.querySelector("#signalJobs");
  if (!jobs.length) {
    el.innerHTML = `<div class="empty">No whale-triggered token analysis jobs yet. When a safe tracked wallet buys a new token, it will appear here.</div>`;
    return;
  }
  el.innerHTML = jobs.map((job) => {
    const status = String(job.status || "QUEUED").toUpperCase();
    const cls = jobStatusClass(status);
    const result = job.final_watchlist_status || job.reason || job.error_message || "Pending";
    return `
      <article class="job-card">
        <div class="job-head">
          <div>
            <span class="job-status ${cls}">${escapeHtml(status)}</span>
            <div class="job-token" title="${escapeHtml(job.token_address)}">${escapeHtml(shortWallet(job.token_address, 5, 5))}</div>
          </div>
          <div class="micro">${escapeHtml(timeText(job.created_at))}</div>
        </div>
        <div class="signal-grid">
          <div class="signal-stat">
            <div class="label">Wallet</div>
            <strong title="${escapeHtml(job.wallet_address)}">${escapeHtml(shortWallet(job.wallet_address, 5, 5))}</strong>
          </div>
          <div class="signal-stat"><div class="label">Signal</div><strong>${escapeHtml(job.signal_type || "N/A")}</strong></div>
        </div>
        <div class="micro" style="margin-top:10px;">${escapeHtml(result)}</div>
      </article>`;
  }).join("");
}

// ---- Page shell + bootstrap ---------------------------------------

function renderShell() {
  const right = `<div class="wr-pulse-state" id="systemStatusBadge"><span class="dot"></span><em id="systemStatus">Ready.</em></div>`;
  return `
    ${BrandBar({ name: "WHALE RADAR", tag: "SMART MONEY · LIVE INTERCEPT", active: "whale", right })}

    <section class="wr-radar-section">
      <div class="wr-radar-card">
        <div class="wr-radar-stage">
          <div class="wr-radar-orb" aria-hidden="true">
            <span class="wr-radar-sweep"></span>
            <span class="wr-radar-ring r1"></span>
            <span class="wr-radar-ring r2"></span>
            <span class="wr-radar-ring r3"></span>
            <span class="wr-radar-pip" id="radarPip"></span>
          </div>
          <div class="wr-radar-readout">
            <div class="wr-readout-eyebrow">LAST INTERCEPT</div>
            <div class="wr-readout-line" id="radarLastWallet">— · —</div>
            <div class="wr-readout-meta" id="radarLastMeta">No live signal yet</div>
          </div>
        </div>
        <div class="wr-radar-rings" id="webhookStatus" data-status="idle">
          <div class="wr-pill"><span class="lbl">WEBHOOK</span><b id="webhookStatusValue">…</b></div>
          <div class="wr-readout-meta" id="webhookNote">Connecting to Helius watcher…</div>
        </div>
      </div>

      <aside class="wr-command-rail">
        <div class="wr-command-title">COMMAND</div>
        <button id="refreshButton" class="wr-cmd primary" type="button">⟳ REFRESH</button>
        <button id="auditButton" class="wr-cmd" type="button">▦ AUDIT WALLETS</button>
        <button id="priceButton" class="wr-cmd" type="button">$ REFRESH PRICES</button>
        <button id="survivalButton" class="wr-cmd" type="button">◈ SURVIVAL PROFILE</button>
        <button id="webhookButton" class="wr-cmd" type="button">⇆ SYNC WEBHOOK</button>
      </aside>
    </section>

    <section class="wr-hud" id="summaryGrid"></section>

    <section class="wr-alerts-grid">
      <article class="wr-panel wr-incoming">
        <header class="wr-panel-head">
          <div>
            <h2><i class="dot pulse"></i> INCOMING — High Signal Alerts</h2>
            <div class="wr-panel-note" id="alertSubtitle">Important BUY / TOKEN_IN events after noise filtering.</div>
          </div>
        </header>
        <div class="alert-grid" id="highSignalAlerts"></div>
      </article>
      <article class="wr-panel wr-confluence">
        <header class="wr-panel-head">
          <div>
            <h2><i class="dot"></i> GROUP BUY — Token Confluence</h2>
            <div class="wr-panel-note" id="confluenceSubtitle">Tokens entered by multiple watched wallets in the same window.</div>
          </div>
        </header>
        <div class="alert-grid" id="confluenceAlerts"></div>
      </article>
    </section>

    <section class="wr-floor">
      <article class="wr-panel wr-leaderboard">
        <header class="wr-panel-head">
          <div>
            <h2><i class="dot"></i> ELITE LEADERBOARD</h2>
            <div class="wr-panel-note">Click a wallet to filter the live feed</div>
          </div>
          <div class="wr-leader-stats">
            <span class="wr-pill"><span class="lbl">TRACKED</span><b id="leaderTotal">—</b></span>
          </div>
        </header>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th><th>Wallet</th><th>Reliability</th><th>Profit</th>
                <th>Win Rate</th><th>Trades</th><th>ROI</th><th>Entry</th>
                <th>Survival</th><th>Style</th><th>Security</th>
              </tr>
            </thead>
            <tbody id="leaderboardRows"></tbody>
          </table>
        </div>
      </article>

      <aside class="wr-panel wr-livefeed">
        <header class="wr-panel-head">
          <div>
            <h2><i class="dot pulse"></i> LIVE FEED</h2>
            <div class="wr-panel-note">Helius webhook events arrive here in real time.</div>
          </div>
          <div class="wr-feed-tools">
            <span class="wr-pill" id="feedFilterLabel"><span class="lbl">FILTER</span><b>ALL WALLETS</b></span>
            <button class="wr-cmd-ghost clear-feed" id="clearFeedFilter" type="button">CLEAR</button>
          </div>
        </header>
        <div class="wr-feed" id="liveFeed"></div>
      </aside>
    </section>

    <section class="wr-panel wr-jobs">
      <header class="wr-panel-head">
        <div>
          <h2><i class="dot"></i> AUTO-ANALYSIS QUEUE</h2>
          <div class="wr-panel-note">Tokens queued when a safe tracked wallet buys.</div>
        </div>
      </header>
      <div class="job-grid" id="signalJobs"></div>
    </section>
  `;
}

async function loadRadar() {
  const params = new URLSearchParams({ limit: selectedWallet ? "300" : "80" });
  if (selectedWallet) params.set("wallet", selectedWallet);
  const r = await fetch(`/api/whale-radar?${params.toString()}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const data = await r.json();

  renderSummary(data);
  renderLeaderboard(data.leaderboard || []);
  renderHighSignalAlerts(data.high_signal_alerts || [], data.signal_settings || {});
  renderConfluenceAlerts(data.confluence_alerts || [], data.signal_settings || {});
  renderFeed(data.live_signals || []);
  renderSignalJobs(data.signal_jobs || []);

  const webhook = data.webhook;
  const webhookStatus = document.querySelector("#webhookStatus");
  const webhookNote   = document.querySelector("#webhookNote");
  const webhookValue  = document.querySelector("#webhookStatusValue");
  if (webhook) {
    if (webhookValue) webhookValue.textContent = `${webhook.status || "UNKNOWN"} · ${webhook.watched_wallets || 0}`;
    if (webhookStatus) webhookStatus.dataset.status = webhook.active ? "active" : (webhook.status || "idle").toLowerCase();
    if (webhookNote) webhookNote.textContent = webhook.last_error
      ? `Last error: ${webhook.last_error}`
      : `Updated ${timeText(webhook.updated_at)}. Active: ${webhook.active ? "yes" : "no"}.`;
  } else {
    if (webhookValue) webhookValue.textContent = "NOT CONFIGURED";
    if (webhookStatus) webhookStatus.dataset.status = "missing";
    if (webhookNote) webhookNote.textContent = "Set Helius webhook credentials and run Sync Webhook.";
  }
}

async function runAction(path, label) {
  const statusEl = document.querySelector("#systemStatus");
  if (statusEl) statusEl.textContent = `${label} running...`;
  const r = await fetch(path, { method: "POST" });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  if (statusEl) statusEl.textContent = `${label} done. ${JSON.stringify(data).slice(0, 180)}`;
  await loadRadar();
}

function attachListeners() {
  const status = document.querySelector("#systemStatus");
  const setStatus = (text) => { if (status) status.textContent = text; };

  // Leaderboard wallet selection / copy.
  document.querySelector("#leaderboardRows").addEventListener("click", (event) => {
    const copyTarget = event.target.closest("[data-copy]");
    if (copyTarget) {
      event.stopPropagation();
      copyText(copyTarget.dataset.copy, copyTarget);
      return;
    }
    const row = event.target.closest(".wallet-row");
    if (!row) return;
    selectedWallet = row.dataset.wallet || null;
    setStatus(selectedWallet
      ? `Showing Live Feed movements for ${shortWallet(selectedWallet, 5, 5)}.`
      : "Ready.");
    loadRadar().catch((error) => setStatus(`Wallet feed load failed: ${error.message}`));
  });

  // Generic copy listeners on each panel.
  ["#liveFeed", "#highSignalAlerts", "#confluenceAlerts", "#signalJobs"].forEach((sel) => {
    document.querySelector(sel).addEventListener("click", (event) => {
      const target = event.target.closest("[data-copy]");
      if (!target) return;
      copyText(target.dataset.copy, target);
    });
  });

  document.querySelector("#clearFeedFilter").addEventListener("click", () => {
    selectedWallet = null;
    setStatus("Showing Live Feed for all wallets.");
    loadRadar().catch((error) => setStatus(`Feed load failed: ${error.message}`));
  });

  document.querySelector("#refreshButton").addEventListener("click", () => {
    setStatus("Refreshing dashboard...");
    loadRadar()
      .then(() => setStatus("Dashboard refreshed."))
      .catch((error) => setStatus(`Refresh failed: ${error.message}`));
  });

  const actions = [
    ["#auditButton",    "/api/whale-radar/audit",          "Wallet audit"],
    ["#priceButton",    "/api/whale-radar/refresh-prices", "Price refresh"],
    ["#survivalButton", "/api/whale-radar/survival",       "Survival profiling"],
    ["#webhookButton",  "/api/whale-radar/sync-webhook",   "Webhook sync"],
  ];
  for (const [sel, path, label] of actions) {
    document.querySelector(sel).addEventListener("click", () => {
      runAction(path, label).catch((error) => setStatus(`${label} failed: ${error.message}`));
    });
  }
}

mount(appEl, renderShell());
attachListeners();

loadRadar().catch((error) => {
  document.querySelector("#summaryGrid").innerHTML = `<article class="metric"><div class="label">Error</div><div class="value">${escapeHtml(error.message)}</div><small>Check the local server and database connection.</small></article>`;
  const status = document.querySelector("#systemStatus");
  if (status) status.textContent = `Load failed: ${error.message}`;
});
