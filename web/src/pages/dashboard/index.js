/**
 * Memeco — COMMAND BRIDGE / SIGNAL FLOOR (Vite-built version).
 *
 * Body of the legacy dashboard <script> imported as-is so behavior
 * matches the existing battle-tested page exactly. Wrapped here in a
 * module that imports the shared cyberpunk styles and the page-specific
 * dashboard.css, plus a small MemecoUtils shim built from format.js
 * because the legacy code references window.MemecoUtils.
 */

import "../../styles/tokens.css";
import "../../styles/cyberpunk.css";
import "./dashboard.css";

import * as memecoFormat from "../../lib/format.js";
import * as memecoTime from "../../lib/time.js";
import * as memecoDom from "../../lib/dom.js";
import "../../components/BrandBar.js";

window.MemecoUtils = Object.freeze({
  escapeHtml:      memecoDom.escapeHtml,
  attr:            memecoDom.escapeHtml,
  numberOrNull:    memecoFormat.numberOrNull,
  asNumber:        memecoFormat.asNumber,
  formatNumber:    memecoFormat.formatNumber,
  formatPercent:   memecoFormat.formatPercent,
  formatMoney:     memecoFormat.formatMoney,
  formatPrice:     memecoFormat.formatPrice,
  formatDate:      memecoTime.formatDate,
  formatAgeMinutes: memecoFormat.formatAgeMinutes,
  shortAddress:    memecoFormat.shortAddress,
  shortWallet:     memecoFormat.shortWallet,
  parseDetails:    memecoFormat.parseDetails,
});

    const summaryEl = document.querySelector("#summary");
    const sideStatsEl = document.querySelector("#sideStats");
    const sideOpportunityCountEl = document.querySelector("#sideOpportunityCount");
    const sideRiskCountEl = document.querySelector("#sideRiskCount");
    const heroOpportunityEl = document.querySelector("#heroOpportunity");
    const opportunityGridEl = document.querySelector("#opportunityGrid");
    const tableCountEl = document.querySelector("#tableCount");
    const rowsEl = document.querySelector("#watchlistRows");
    const statusNoteEl = document.querySelector("#statusNote");
    const liveDotEl = document.querySelector("#liveDot");
    const freshnessEl = document.querySelector("#freshness");
    const refreshButtonEl = document.querySelector("#refreshButton");
    const scanButtonEl = document.querySelector("#scanButton");
    const scanNoteEl = document.querySelector("#scanNote");
    const scanTimeEl = document.querySelector("#scanTime");
    const scanStepsEl = document.querySelector("#scanSteps");
    const scanErrorEl = document.querySelector("#scanError");
    const systemLoadMeterEl = document.querySelector("#systemLoadMeter");
    const loadGaugeEl = document.querySelector("#loadGauge");
    const loadValueEl = document.querySelector("#loadValue");
    const loadStatusEl = document.querySelector("#loadStatus");
    const loadHintEl = document.querySelector("#loadHint");
    const manualAnalyzeFormEl = document.querySelector("#manualAnalyzeForm");
    const manualTokenInputEl = document.querySelector("#manualTokenInput");
    const manualAnalyzeButtonEl = document.querySelector("#manualAnalyzeButton");

    // Shared formatting helpers come from /static/shared/utils.js.
    // The <script src="..."> tag in <head> is synchronous (no defer),
    // so MemecoUtils is guaranteed to be defined here.
    const {
      escapeHtml,
      parseDetails,
      asNumber,
      formatDate,
      formatAgeMinutes,
      formatPrice,
    } = window.MemecoUtils;

    // Page-local formatters intentionally diverge from MemecoUtils:
    //   formatMoney   — uses 0/1/2 decimals (vs shared 2/2/2) for tighter rows.
    //   formatPercent — returns "unknown" (not "N/A") and forces 2 decimals
    //                   even for 0%, matching this dashboard's existing UI.
    function formatMoney(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return "N/A";
      if (number >= 1_000_000) return `$${(number / 1_000_000).toFixed(2)}M`;
      if (number >= 1_000) return `$${(number / 1_000).toFixed(1)}K`;
      return `$${number.toFixed(0)}`;
    }

    function formatLiquidityValue(row, value) {
      if (value !== null && value !== undefined && value !== "") return formatMoney(value);
      if (row.bonding_curve_status === "PUMPFUN_BONDING") return "Bonding";
      return "No DEX liq";
    }

    function formatPercent(value) {
      if (value === null || value === undefined || value === "") return "unknown";
      const number = Number(value);
      return Number.isFinite(number) ? `${number.toFixed(2)}%` : "unknown";
    }

    function badgeClass(status) {
      if (!status) return "";
      if (status.includes("PASS")) return "pass";
      if (status.includes("REJECT")) return "reject";
      if (status.includes("WAIT")) return "wait";
      return "";
    }

    // ---- Pipeline stop-stage detection ---------------------------------
    //
    // Memeco short-circuits the 9-stage pipeline as soon as a gate fails,
    // so a token that flunked Market never has Wallet / Cluster / etc.
    // run. The dashboard surfaces three different states so users don't
    // assume "blank cell == bug":
    //   actual data  → stage ran and returned values
    //   "Unknown"    → stage ran but the upstream API gave no answer
    //   "—"          → stage was skipped because the pipeline stopped
    //                   earlier (`PIPELINE_STAGES`).
    //
    // The decision column also gets a "Stopped at: X" pill explaining
    // where the pipeline halted, so the empty cells make sense at a
    // glance.
    const PIPELINE_STAGES = [
      "Market",
      "Contract",
      "Liquidity",
      "Wallet",
      "Cluster",
      "Manipulation",
      "Intelligence",
      "Final",
    ];

    function pipelineStopIndex(status) {
      // Returns the index in PIPELINE_STAGES where the pipeline halted.
      // Returns null if the pipeline ran end-to-end (any final pass
      // status) or the status is unrecognised.
      const value = String(status || "");
      if (value === "WATCHLIST_PASS" || value === "WATCHLIST_PASS_HIGH_RISK"
          || value === "WATCHLIST_REVIEW") return null;
      if (value === "WATCHLIST_REJECT_MARKET") return 0;
      if (value === "WATCHLIST_REJECT_CONTRACT_RISK") return 1;
      if (value === "WATCHLIST_WAIT_LIQUIDITY"
          || value === "WATCHLIST_REJECT_LIQUIDITY") return 2;
      if (value === "WATCHLIST_WAIT_SECURITY_DATA"
          || value === "WATCHLIST_REJECT_WALLET_RISK") return 3;
      if (value === "WATCHLIST_REJECT_WALLET_INTELLIGENCE") return 6;
      if (value === "WATCHLIST_REJECT_WALLET_MANIPULATION") return 5;
      return null;
    }

    function pipelineStopName(status) {
      const idx = pipelineStopIndex(status);
      return idx === null ? null : PIPELINE_STAGES[idx];
    }

    function stageWasSkipped(status, stageIndex) {
      // True when this row's pipeline stopped strictly before stageIndex,
      // so we should render "—" instead of "Pending"/"Unknown".
      const stopIdx = pipelineStopIndex(status);
      return stopIdx !== null && stageIndex > stopIdx;
    }

    function notRunLabel(title = "Stage skipped — earlier gate halted pipeline") {
      return `<span class="risk-label not-run" title="${escapeHtml(title)}">—</span>`;
    }

    function shortStatus(status) {
      return String(status || "PENDING")
        .replace("WATCHLIST_", "")
        .replace("CONTRACT_", "")
        .replace("LIQUIDITY_", "")
        .replace("WALLET_", "")
        .replace("MARKET_", "")
        .replaceAll("_", " ");
    }

    function finalDecisionLabel(status) {
      const value = String(status || "PENDING");
      if (value === "WATCHLIST_PASS") return "PASS";
      if (value === "WATCHLIST_PASS_HIGH_RISK") return "HIGH RISK";
      if (value === "WATCHLIST_WAIT_SECURITY_DATA") return "WAIT SECURITY";
      if (value === "WATCHLIST_WAIT_LIQUIDITY") return "WAIT LIQUIDITY";
      if (value === "WATCHLIST_REJECT_MARKET") return "REJECT MARKET";
      if (value === "WATCHLIST_REJECT_CONTRACT_RISK") return "REJECT CONTRACT";
      if (value === "WATCHLIST_REJECT_LIQUIDITY") return "REJECT LIQUIDITY";
      if (value === "WATCHLIST_REJECT_WALLET_RISK") return "REJECT WALLET";
      if (value === "WATCHLIST_REJECT_WALLET_INTELLIGENCE") return "REJECT INTEL";
      if (value === "WATCHLIST_REVIEW") return "REVIEW";
      return shortStatus(value);
    }

    function stackLine(key, value, title = "") {
      return `
        <div class="stack-line" ${title ? `title="${escapeHtml(title)}"` : ""}>
          <span class="stack-key">${escapeHtml(key)}</span>
          <span class="stack-value">${value}</span>
        </div>
      `;
    }

    function formatBondingStatus(row) {
      const status = row.bonding_curve_status || "";
      const progress = row.bonding_curve_progress;
      if (status === "NOT_ON_DEX") return `<span class="risk-label warning" title="No pairCreatedAt found">Not on DEX</span>`;
      if (status === "PUMPFUN_BONDING") {
        const label = progress === null || progress === undefined ? "Bonding" : `Bonding ${Number(progress).toFixed(1)}%`;
        return `<span class="risk-label warning" title="Pump.fun token visible on DexScreener">${label}</span>`;
      }
      if (status === "DEX_LISTED") return `<span class="risk-label low" title="Token has a DEX pair outside Pump.fun bonding">DEX listed</span>`;
      return `<span class="risk-label">N/A</span>`;
    }

    function formatDexAds(row) {
      const activeBoosts = asNumber(row.dex_active_boosts);
      const paidOrderCount = asNumber(row.dex_paid_order_count);
      const boostOrderCount = asNumber(row.dex_boost_order_count);
      const orderTypes = parseDetails(row.dex_paid_order_types);
      const typeLabels = Array.isArray(orderTypes)
        ? orderTypes.map((type) => String(type || "").replace("tokenProfile", "Profile"))
        : [];

      if (activeBoosts >= 500) return `<span class="ad-pill golden" title="DexScreener Golden Ticker">Golden ${activeBoosts}</span>`;
      if (activeBoosts > 0) return `<span class="ad-pill boost" title="Active DexScreener boosts">Boost ${activeBoosts}</span>`;
      if (boostOrderCount > 0) return `<span class="ad-pill boost" title="DexScreener boost order detected">Boost order</span>`;
      if (paidOrderCount > 0 || typeLabels.length) {
        const label = typeLabels.length ? typeLabels.join(", ") : "Paid";
        return `<span class="ad-pill profile" title="DexScreener paid order detected">${escapeHtml(label)}</span>`;
      }
      return `<span class="ad-pill" title="No DexScreener paid order or active boost found">None</span>`;
    }

    function normalizedRiskScore(row) {
      const status = row.contract_risk_status || "";
      const rawScore = asNumber(row.risk_score);
      const topHolders = asNumber(row.top_holders_percent);
      if (status === "CONTRACT_PASS") return clampScore(1 + rawRiskBonus(rawScore, 1));
      if (status === "CONTRACT_WARNING") return clampScore(4 + rawRiskBonus(rawScore, 2) + holderRiskBonus(topHolders));
      if (status === "CONTRACT_DANGER") return clampScore(7 + rawRiskBonus(rawScore, 2) + holderRiskBonus(topHolders));
      return "";
    }

    function rawRiskBonus(rawScore, maxBonus) {
      if (!rawScore || rawScore <= 0) return 0;
      return Math.min(maxBonus, Math.log10(rawScore + 1) / 3 * maxBonus);
    }

    function holderRiskBonus(topHolders) {
      if (!topHolders || topHolders < 50) return 0;
      if (topHolders >= 90) return 1.5;
      if (topHolders >= 70) return 1;
      return 0.5;
    }

    function clampScore(value) {
      return Math.max(0, Math.min(10, Math.round(value)));
    }

    function formatRisk(row) {
      const status = row.contract_risk_status || "";
      const rawScore = row.risk_score ?? "";
      const score10 = normalizedRiskScore(row);
      let label = "Pending";
      let className = "";
      if (status === "CONTRACT_DANGER") {
        label = `Danger ${score10}/10`;
        className = "danger";
      } else if (status === "CONTRACT_WARNING") {
        label = `Warning ${score10}/10`;
        className = "warning";
      } else if (status === "CONTRACT_PASS") {
        label = `Low ${score10}/10`;
        className = "low";
      } else if (status === "CONTRACT_UNKNOWN") {
        label = "Unknown";
        className = "warning";
      } else if (stageWasSkipped(row.final_watchlist_status, 1)) {
        return notRunLabel();
      }
      const title = rawScore === "" || rawScore === null ? "" : `Raw RugCheck score: ${Number(rawScore).toLocaleString()}`;
      return `<span class="risk-label ${className}" title="${escapeHtml(title)}">${escapeHtml(label)}</span>`;
    }

    function formatWalletRisk(row) {
      const status = row.wallet_status || "";
      const top10 = formatPercent(row.top10_holders_percent);
      if (status === "WALLET_DANGER") return `<span class="risk-label danger" title="Top 10 holders: ${top10}">Danger</span>`;
      if (status === "WALLET_WARNING") return `<span class="risk-label warning" title="Top 10 holders: ${top10}">Warning</span>`;
      if (status === "WALLET_PASS") return `<span class="risk-label low" title="Top 10 holders: ${top10}">Pass</span>`;
      if (status === "WALLET_UNKNOWN") return `<span class="risk-label warning">Unknown</span>`;
      if (stageWasSkipped(row.final_watchlist_status, 3)) return notRunLabel();
      return `<span class="risk-label">Pending</span>`;
    }

    function formatLiquidityTrap(row) {
      const details = parseDetails(row.details);
      const status = String(details.liquidity_trap_status || "LIQUIDITY_TRAP_UNKNOWN");
      const score = asNumber(details.liquidity_trap_score);
      const reason = details.liquidity_trap_reason || "";
      const lpLock = details.lp_lock || {};
      const warnings = Array.isArray(details.liquidity_trap_warnings) ? details.liquidity_trap_warnings : [];
      // Liquidity trap is computed during the Liquidity stage. Render a
      // dash when the pipeline halted before that point and we have no
      // score to show.
      if (!details.liquidity_trap_score
          && status === "LIQUIDITY_TRAP_UNKNOWN"
          && stageWasSkipped(row.final_watchlist_status, 2)) {
        return notRunLabel();
      }
      let className = "low";
      let level = "LOW";
      if (status.includes("CRITICAL")) {
        className = "critical";
        level = "CRITICAL";
      } else if (status.includes("HIGH")) {
        className = "high";
        level = "HIGH";
      } else if (status.includes("MEDIUM") || status.includes("UNKNOWN")) {
        className = "medium";
        level = status.includes("UNKNOWN") ? "UNKNOWN" : "MEDIUM";
      }
      const title = [reason, lpLock.lp_reason, ...warnings].filter(Boolean).join(" | ");
      const detail = lpLock.lp_locked_pct !== undefined && lpLock.lp_locked_pct !== null ? `${lpLock.lp_locked_pct}% LP` : level;
      return `
        <span class="probability-cell ${className}" title="${escapeHtml(title || "No strong liquidity trap pattern detected")}">
          ${score}/100
          <span class="probability-detail">${escapeHtml(detail)}</span>
        </span>
      `;
    }

    function formatClusterRisk(row) {
      const status = row.cluster_status || "";
      const size = row.largest_cluster_size ?? 0;
      if (status === "CLUSTER_DANGER") return `<span class="risk-label danger" title="Largest shared funder cluster: ${size} holders">Danger</span>`;
      if (status === "CLUSTER_WARNING") return `<span class="risk-label warning" title="Largest shared funder cluster: ${size} holders">Warning</span>`;
      if (status === "CLUSTER_PASS") return `<span class="risk-label low" title="No shared funding-source cluster detected">Pass</span>`;
      if (status === "CLUSTER_UNKNOWN") return `<span class="risk-label warning">Unknown</span>`;
      if (stageWasSkipped(row.final_watchlist_status, 4)) return notRunLabel();
      return `<span class="risk-label">Pending</span>`;
    }

    function formatManipulationRisk(row) {
      const status = row.manipulation_status || "";
      const score = row.manipulation_score ?? "";
      const reason = row.manipulation_reason || "";
      const title = [
        reason,
        `Shared funder: ${row.shared_funder_cluster_size ?? 0}`,
        `Token split: ${row.token_distributor_count ?? 0}`,
        `Linked: ${row.linked_wallet_count ?? 0}`,
        `Dump: ${row.coordinated_dump_count ?? 0}`,
      ].filter(Boolean).join(" | ");

      if (status === "MANIPULATION_DANGER") {
        return `<span class="manipulation-cell danger" title="${escapeHtml(title)}">Danger ${escapeHtml(score)}/10<span class="manipulation-detail">Suspicious</span></span>`;
      }
      if (status === "MANIPULATION_WARNING") {
        return `<span class="manipulation-cell warning" title="${escapeHtml(title)}">Warning ${escapeHtml(score)}/10<span class="manipulation-detail">Review links</span></span>`;
      }
      if (status === "MANIPULATION_PASS") {
        return `<span class="manipulation-cell low" title="${escapeHtml(title)}">Pass<span class="manipulation-detail">No strong pattern</span></span>`;
      }
      if (status === "MANIPULATION_UNKNOWN") return `<span class="risk-label warning" title="${escapeHtml(title)}">Unknown</span>`;
      if (stageWasSkipped(row.final_watchlist_status, 5)) return notRunLabel();
      return `<span class="risk-label">Pending</span>`;
    }

    function formatIntelligence(row) {
      const summary = parseDetails(row.intelligence_summary) || {};
      const items = [
        ["Smart", summary.smart_wallets || 0],
        ["Fresh", summary.fresh_wallets || 0],
        ["Sniper", summary.snipers || 0],
        ["Whale", summary.whales || 0],
        ["Dumper", summary.dumpers || 0],
        ["Dev", summary.dev_related || 0],
        ["Bot", summary.bots || 0],
      ].filter((item) => Number(item[1]) > 0);
      if (items.length) {
        return `
          <div class="intel-list" title="Average wallet score: ${escapeHtml(summary.avg_wallet_score ?? "n/a")}">
            ${items.map(([label, count]) => `<span class="intel-pill">${escapeHtml(label)} ${escapeHtml(count)}</span>`).join("")}
          </div>
        `;
      }
      // No signals — distinguish "stage skipped" from "stage ran clean".
      if (stageWasSkipped(row.final_watchlist_status, 6)) return notRunLabel();
      return `<span class="risk-label">None</span>`;
    }

    function formatDevAudit(row) {
      const details = parseDetails(row.details);
      const status = String(details.dev_audit_status || "DEV_UNKNOWN");
      const reason = details.dev_audit_reason || "";
      const sold = asNumber(details.dev_sold_token_amount);
      const out = asNumber(details.dev_total_token_out);
      let className = "medium";
      let label = "Unknown";
      if (status === "DEV_HOLDING") {
        className = "low";
        label = "Holding";
      } else if (status === "DEV_SOLD_PARTIAL") {
        className = "high";
        label = "Sold";
      } else if (status === "DEV_SOLD_OUT") {
        className = "critical";
        label = "Sold out";
      } else if (status === "DEV_TRANSFERRED_TOKENS") {
        className = "high";
        label = "Moved";
      } else if (status === "DEV_NO_BALANCE") {
        className = "high";
        label = "No balance";
      } else if (stageWasSkipped(row.final_watchlist_status, 5)) {
        // Dev audit only runs after Manipulation; render dash when the
        // pipeline halted earlier instead of leaking the raw "Unknown".
        return notRunLabel();
      }
      const title = [
        reason,
        details.dev_wallet_address ? `Dev: ${details.dev_wallet_address}` : "",
        `Sold: ${sold.toLocaleString()}`,
        `Out: ${out.toLocaleString()}`,
      ].filter(Boolean).join(" | ");
      const detail = sold > 0 ? sold.toLocaleString(undefined, { maximumFractionDigits: 0 }) : status.replace("DEV_", "");
      return `<span class="probability-cell ${className}" title="${escapeHtml(title)}">${escapeHtml(label)}<span class="probability-detail">${escapeHtml(detail)}</span></span>`;
    }

    function formatInsiderProbability(row) {
      const details = parseDetails(row.details);
      const score = asNumber(details.insider_probability_score);
      const level = String(details.insider_probability_level || "LOW");
      const reasons = Array.isArray(details.insider_probability_reasons) ? details.insider_probability_reasons : [];
      // Insider probability is computed from intel + manipulation; if we
      // never even got there, render a clean dash.
      if (!details.insider_probability_score
          && stageWasSkipped(row.final_watchlist_status, 6)) {
        return notRunLabel();
      }
      const className = level.toLowerCase();
      const title = reasons.length ? reasons.join(" | ") : "No strong insider signal";
      return `<span class="probability-cell ${className}" title="${escapeHtml(title)}">${score}/100<span class="probability-detail">${escapeHtml(level)}</span></span>`;
    }

    function compactSignal(label, html) {
      return stackLine(label, html);
    }

    function formatMarketStack(row) {
      return `
        <div class="stack-cell">
          ${stackLine("Pair", formatAgeMinutes(row.pair_age_minutes), row.pair_created_at || "")}
          ${stackLine("Dex", formatAgeMinutes(row.dexscreener_age_minutes), row.dexscreener_first_seen_at || "")}
          ${stackLine("State", formatBondingStatus(row))}
          ${stackLine("Ads", formatDexAds(row))}
        </div>
      `;
    }

    function formatLiquidityStack(row) {
      const details = parseDetails(row.details);
      const lpLock = details.lp_lock || {};
      const lpLabel = lpLock.lp_locked_pct !== undefined && lpLock.lp_locked_pct !== null
        ? `${lpLock.lp_locked_pct}%`
        : String(lpLock.lp_lock_status || "Unknown").replace("LP_", "");
      return `
        <div class="stack-cell">
          ${stackLine("Trap", formatLiquidityTrap(row))}
          ${stackLine("LP", escapeHtml(lpLabel), lpLock.lp_reason || "")}
          ${stackLine("Liq", escapeHtml(formatMoney(details.liquidity_usd)))}
          ${stackLine("MCap", escapeHtml(formatMoney(details.market_cap_usd)))}
        </div>
      `;
    }

    function formatWalletSignals(row) {
      return `
        <div class="stack-cell">
          ${compactSignal("Wallet", formatWalletRisk(row))}
          ${compactSignal("Cluster", formatClusterRisk(row))}
          ${compactSignal("Manip", formatManipulationRisk(row).replaceAll("manipulation-cell", "manipulation-cell compact"))}
          ${compactSignal("Dev", formatDevAudit(row).replaceAll("probability-cell", "probability-cell compact"))}
          ${compactSignal("Intel", formatIntelligence(row))}
        </div>
      `;
    }

    function statusTone(status) {
      const value = String(status || "");
      if (value.includes("DANGER") || value.includes("REJECT") || value.includes("SOLD") || value.includes("NO_BALANCE") || value.includes("HIGH") || value.includes("CRITICAL")) return "danger";
      if (value.includes("WARNING") || value.includes("WAIT") || value.includes("UNKNOWN") || value.includes("MEDIUM")) return "warning";
      if (value.includes("PASS") || value.includes("LOW") || value.includes("STRONG") || value.includes("LOCKED") || value.includes("HOLDING")) return "low";
      return "";
    }

    function miniPill(label, value = "", tone = "", title = "") {
      const text = value === "" || value === null || value === undefined ? label : label ? `${label} ${value}` : value;
      return `<span class="mini-pill ${tone}" ${title ? `title="${escapeHtml(title)}"` : ""}>${escapeHtml(text)}</span>`;
    }

    // Pill helper for table cells that knows about pipeline stop stages.
    // Renders the regular `miniPill` when we have data, or a muted "—"
    // pill labelled with the stage name when the row's pipeline stopped
    // before that stage ran. This is what makes "REJECT_MARKET" rows
    // stop showing "Pending Pending Pending" cells past the Market gate.
    function stagePill(row, stageIdx, label, value, tone, title) {
      if (!value && stageWasSkipped(row.final_watchlist_status, stageIdx)) {
        return `<span class="mini-pill not-run" title="Stage skipped — pipeline halted earlier">${escapeHtml(label)} —</span>`;
      }
      return miniPill(label, value, tone, title);
    }

    function marketStat(label, value, title = "") {
      return `
        <div class="market-stat" ${title ? `title="${escapeHtml(title)}"` : ""}>
          <span class="stat-label">${escapeHtml(label)}</span>
          <span class="stat-value">${escapeHtml(value)}</span>
        </div>
      `;
    }

    function formatShortDate(value) {
      if (!value) return "N/A";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "N/A";
      return date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    function formatDexEntryTime(row) {
      if (!row.pair_created_at) return "DEX entry N/A";
      return `DEX listed ${formatShortDate(row.pair_created_at)}`;
    }

    function formatTableOpportunity(row) {
      const txns5m = asNumber(row.buys_5m) + asNumber(row.sells_5m);
      const txns1h = asNumber(row.buys_1h) + asNumber(row.sells_1h);
      return `
        <div class="table-cell">
          <div class="signal-pills">
            ${miniPill("DEX", formatAgeMinutes(row.dexscreener_age_minutes), "accent", row.dexscreener_first_seen_at || "")}
            ${formatDexAds(row)}
          </div>
          <div class="market-snapshot">
            ${marketStat("Price", formatPrice(row.price_usd))}
            ${marketStat("FDV", formatMoney(row.fdv_usd))}
            ${marketStat("Vol 5m", formatMoney(row.volume_5m_usd))}
            ${marketStat("Tx 5m", txns5m)}
            ${marketStat("Vol 1h", formatMoney(row.volume_1h_usd))}
            ${marketStat("Tx 1h", txns1h)}
          </div>
        </div>
      `;
    }

    function formatTableSafety(row) {
      const details = rowDetails(row);
      const insider = asNumber(details.insider_probability_score);
      const score10 = normalizedRiskScore(row);
      const insiderText = insider > 0 || details.insider_probability_score
        ? `${insider}/100`
        : "";
      return `
        <div class="table-cell">
          <div class="signal-pills">
            ${stagePill(row, 1, "Contract", shortStatus(row.contract_risk_status), statusTone(row.contract_risk_status))}
            ${stagePill(row, 6, "Insider",  insiderText, statusTone(details.insider_probability_level || "LOW"))}
          </div>
          <div class="cell-sub">Risk ${score10 || (stageWasSkipped(row.final_watchlist_status, 1) ? "—" : "N/A")}/10</div>
        </div>
      `;
    }

    function formatTableLiquidity(row) {
      const details = rowDetails(row);
      const lpLock = details.lp_lock || {};
      const lpLabel = lpLock.lp_locked_pct !== undefined && lpLock.lp_locked_pct !== null
        ? `${lpLock.lp_locked_pct}% LP`
        : String(lpLock.lp_lock_status || "LP unknown").replace("LP_", "").replaceAll("_", " ");
      const trapValue = details.liquidity_trap_score
        ? `${liquidityTrapScore(row)}/100`
        : "";
      // Liquidity + market cap as a vertical stacked cell. Saves the
      // horizontal real estate the old 6-tile market-snapshot grid ate
      // and keeps both numbers visible side-by-side without scrolling.
      const liqValue = formatLiquidityValue(row, row.liquidity_usd || details.liquidity_usd);
      const mcapValue = formatMoney(row.market_cap_usd || details.market_cap_usd);
      const vol24Value = formatMoney(row.volume_24h_usd || details.volume_24h_usd);
      const buys = asNumber(row.buys_24h);
      const sells = asNumber(row.sells_24h);
      return `
        <div class="table-cell">
          <div class="signal-pills">
            ${stagePill(row, 2, "Trap", trapValue, statusTone(details.liquidity_trap_status))}
            ${stagePill(row, 2, "", lpLock.lp_lock_status ? lpLabel : "", statusTone(lpLock.lp_lock_status), lpLock.lp_reason || "")}
          </div>
          <div class="liq-mcap-stack">
            <div class="liq-row"><span class="lbl">Liq</span><span class="val">${escapeHtml(liqValue)}</span></div>
            <div class="liq-row"><span class="lbl">MCap</span><span class="val">${escapeHtml(mcapValue)}</span></div>
            <div class="liq-row sub"><span class="lbl">Vol 24h</span><span class="val">${escapeHtml(vol24Value)}</span></div>
            <div class="liq-row sub"><span class="lbl">B/S 24h</span><span class="val">${buys}/${sells}</span></div>
          </div>
        </div>
      `;
    }

    function formatTableWallet(row) {
      const details = rowDetails(row);
      const summary = parseDetails(row.intelligence_summary) || {};
      const devStatus = details.dev_audit_status || "";
      const devFlowStatus = details.dev_flow_status || "";
      const manipValue = row.manipulation_score !== null && row.manipulation_score !== undefined
        ? `${row.manipulation_score}/10`
        : "";
      const shadowValue = details.shadow_dev_score !== null && details.shadow_dev_score !== undefined
        ? `${asNumber(details.shadow_dev_score)}/100`
        : "";
      return `
        <div class="table-cell">
          <div class="signal-pills">
            ${stagePill(row, 3, "Wallet",  shortStatus(row.wallet_status),     statusTone(row.wallet_status), `Top10: ${formatPercent(row.top10_holders_percent)}`)}
            ${stagePill(row, 4, "Cluster", shortStatus(row.cluster_status),    statusTone(row.cluster_status))}
            ${stagePill(row, 5, "Manip",   manipValue,                          statusTone(row.manipulation_status), row.manipulation_reason || "")}
            ${stagePill(row, 5, "Dev",     devStatus ? shortStatus(devStatus) : "",   statusTone(devStatus), details.dev_audit_reason || "")}
            ${stagePill(row, 5, "Shadow",  shadowValue,                         statusTone(devFlowStatus), details.dev_flow_reason || "")}
          </div>
          <div class="market-snapshot compact">
            ${marketStat("Early", asNumber(summary.early_buyers))}
            ${marketStat("Profit", asNumber(summary.early_profitable))}
            ${marketStat("Exited", asNumber(summary.early_exited))}
            ${marketStat("Bots", asNumber(summary.bots))}
            ${marketStat("Dumpers", asNumber(summary.dumpers))}
            ${marketStat("Snipers", asNumber(summary.snipers))}
          </div>
        </div>
      `;
    }

    function formatTableDecision(row) {
      const stop = pipelineStopName(row.final_watchlist_status);
      const stopBadge = stop
        ? `<span class="stage-stop" title="Pipeline halted at ${escapeHtml(stop)} — downstream stages were skipped on purpose">⛔ Stopped at ${escapeHtml(stop)}</span>`
        : "";
      // Timestamp + per-row toolbar live inside the Decision cell now
      // that it's the rightmost (sticky) column. Saves a whole column
      // of horizontal real estate.
      return `
        <div class="table-cell decision-cell">
          <div class="cell-primary">
            <span class="badge ${badgeClass(row.final_watchlist_status)}">${escapeHtml(finalDecisionLabel(row.final_watchlist_status))}</span>
            ${decisionFlipBadge(row)}
          </div>
          ${stopBadge}
          <div class="cell-sub two-lines">${escapeHtml(row.final_watchlist_reason || "No final reason")}</div>
          <div class="decision-time" title="${escapeHtml(row.created_at || "")}">${escapeHtml(formatShortDate(row.created_at))}</div>
          ${rowToolbar(row)}
        </div>
      `;
    }

    function tokenLogo(row, size = "normal") {
      const symbol = escapeHtml(row.symbol || "?");
      const initials = escapeHtml(String(row.symbol || "?").slice(0, 2).toUpperCase());
      const extra = size === "hero" ? " hero-logo" : "";
      if (!row.logo_url) {
        return `<span class="token-logo token-fallback${extra}">${initials}</span>`;
      }
      return `
        <span class="token-logo token-fallback is-hidden${extra}">${initials}</span>
        <img
          class="token-logo${extra}"
          src="${escapeHtml(row.logo_url)}"
          alt="${symbol}"
          loading="lazy"
          referrerpolicy="no-referrer"
          onerror="this.style.display='none'; this.previousElementSibling.classList.remove('is-hidden')"
        >
      `;
    }

    function copyIcon() {
      return `
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" stroke-width="2"></rect>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="currentColor" stroke-width="2"></path>
        </svg>
      `;
    }

    function tokenDetailUrl(row) {
      return `/token?run_id=${encodeURIComponent(row.run_id)}&token_id=${encodeURIComponent(row.token_id)}`;
    }

    function rowDetails(row) {
      return parseDetails(row.details);
    }

    function insiderScore(row) {
      return asNumber(rowDetails(row).insider_probability_score);
    }

    function liquidityTrapScore(row) {
      return asNumber(rowDetails(row).liquidity_trap_score);
    }

    function opportunityScore(row) {
      const details = rowDetails(row);
      const passBoost = row.final_watchlist_pass ? 80 : String(row.final_watchlist_status || "").includes("PASS_HIGH_RISK") ? 55 : 0;
      const marketBoost = row.market_filter_pass ? 18 : 0;
      const contractBoost = row.contract_risk_pass ? 16 : 0;
      const liquidityBoost = String(details.liquidity_status || "").includes("STRONG") ? 18 : 0;
      const adBoost = Math.min(18, asNumber(row.dex_active_boosts) / 40 + asNumber(row.dex_paid_order_count) * 2);
      const riskPenalty = insiderScore(row) * .6 + liquidityTrapScore(row) * .35;
      const walletPenalty = String(row.wallet_status || "").includes("DANGER") ? 25 : 0;
      return passBoost + marketBoost + contractBoost + liquidityBoost + adBoost - riskPenalty - walletPenalty;
    }

    function bestOpportunityRows(rows) {
      return [...rows].sort((a, b) => opportunityScore(b) - opportunityScore(a)).slice(0, 3);
    }

    function movementTone(value) {
      const numeric = Number(value);
      if (value === null || value === undefined || value === "" || !Number.isFinite(numeric)) return "unknown";
      if (numeric > 0) return "up";
      if (numeric < 0) return "down";
      return "flat";
    }

    function formatMovementPct(value) {
      const numeric = Number(value);
      if (value === null || value === undefined || value === "" || !Number.isFinite(numeric)) return "N/A";
      const sign = numeric > 0 ? "+" : "";
      return `${sign}${numeric.toFixed(Math.abs(numeric) >= 100 ? 0 : 2)}%`;
    }

    function dexscreenerChange(row, key) {
      const changes = parseDetails(row.dexscreener_price_change);
      return changes && Object.prototype.hasOwnProperty.call(changes, key) ? changes[key] : null;
    }

    function movementValue(row, key, fallbackKey) {
      const ownValue = row[key];
      if (ownValue !== null && ownValue !== undefined && ownValue !== "") return ownValue;
      return dexscreenerChange(row, fallbackKey);
    }

    function renderSparkline(row) {
      // Inline SVG: tiny price trend chart from the last ~24 hours.
      // Server returns up to 24 hourly close prices in chronological
      // order via row.price_sparkline (JSONB array of numbers).
      const raw = row.price_sparkline;
      const points = Array.isArray(raw)
        ? raw
        : typeof raw === "string"
          ? (() => { try { return JSON.parse(raw); } catch (e) { return []; } })()
          : [];
      // Need at least 2 points to draw a line.
      const numbers = points
        .map((p) => Number(p))
        .filter((n) => Number.isFinite(n) && n > 0);
      if (numbers.length < 2) return "";

      const width = 64;
      const height = 20;
      const min = Math.min(...numbers);
      const max = Math.max(...numbers);
      const range = max - min || max || 1;   // avoid div-by-zero on a flat line
      const stepX = numbers.length > 1 ? width / (numbers.length - 1) : 0;
      const path = numbers
        .map((value, index) => {
          const x = (index * stepX).toFixed(2);
          // Higher values render *higher* on screen (smaller y).
          const y = (height - ((value - min) / range) * height).toFixed(2);
          return `${index === 0 ? "M" : "L"}${x},${y}`;
        })
        .join(" ");

      const direction = numbers[numbers.length - 1] >= numbers[0] ? "up" : "down";
      const last = numbers[numbers.length - 1];
      const tooltip = `24h: ${formatPrice(min)} → ${formatPrice(last)} (peak ${formatPrice(max)})`;

      return `
        <span class="sparkline ${direction}" title="${escapeHtml(tooltip)}" aria-hidden="true">
          <svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" preserveAspectRatio="none">
            <path d="${path}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
      `;
    }

    function renderMovementStrip(row) {
      const windows = [
        ["1h", movementValue(row, "price_change_1h_pct", "h1")],
        ["4h", movementValue(row, "price_change_4h_pct", "h6")],
        ["24h", movementValue(row, "price_change_24h_pct", "h24")],
      ];
      return `
        <div class="movement-strip" title="Price movement from the latest stored price snapshot">
          ${renderSparkline(row)}
          ${windows.map(([label, value]) => `
            <span class="movement-chip ${movementTone(value)}">
              <span class="move-label">${label}</span>
              ${escapeHtml(formatMovementPct(value))}
            </span>
          `).join("")}
        </div>
      `;
    }

    function renderTokenIdentity(row, withName = true) {
      const starHtml = isStarred(row.token_address)
        ? `<span class="star-mark" aria-label="Starred">★</span>`
        : "";
      return `
        <div class="token-wrap">
          ${tokenLogo(row)}
          <div class="token-meta">
            <div class="symbol">
              <a class="symbol-link" href="${tokenDetailUrl(row)}" title="Open token details">${escapeHtml(row.symbol || "Unknown")}</a>${starHtml}
            </div>
            <div class="token-name" title="${escapeHtml(row.pair_created_at || "")}">${escapeHtml(formatDexEntryTime(row))}</div>
            ${withName ? `<div class="token-name">${escapeHtml(row.name || "")}</div>` : ""}
            <div class="address-line">
              <div class="address" title="${escapeHtml(row.token_address || "")}">${escapeHtml(row.token_address || "")}</div>
              <button class="copy-button" type="button" aria-label="Copy token address" title="Copy token address" data-address="${escapeHtml(row.token_address || "")}">${copyIcon()}</button>
            </div>
            ${renderMovementStrip(row)}
          </div>
        </div>
      `;
    }

    function renderCardTokenIdentity(row) {
      return `
        <div class="token-wrap">
          ${tokenLogo(row)}
          <div class="token-meta">
            <div class="symbol">
              <a class="symbol-link" href="${tokenDetailUrl(row)}" title="Open token details">${escapeHtml(row.symbol || "Unknown")}</a>
            </div>
            <div class="token-name">${escapeHtml(row.name || row.token_address || "")}</div>
            ${renderMovementStrip(row)}
          </div>
        </div>
      `;
    }

    function renderHero(rows) {
      const [row] = bestOpportunityRows(rows);
      if (!row) {
        heroOpportunityEl.innerHTML = `
          <div class="hero-content">
            <div>
              <div class="hero-eyebrow">Opportunity engine</div>
              <div class="hero-symbol">No tokens yet</div>
              <div class="hero-name">Run a scan or analyze a token manually.</div>
            </div>
          </div>
        `;
        return;
      }
      const details = rowDetails(row);
      heroOpportunityEl.innerHTML = `
        <div class="hero-content">
          <div>
            <div class="hero-eyebrow">Best current opportunity</div>
            <div class="hero-token">
              ${tokenLogo(row, "hero")}
              <div>
                <div class="hero-symbol">${escapeHtml(row.symbol || "Unknown")}</div>
                <div class="hero-name">${escapeHtml(row.name || row.token_address || "")}</div>
              </div>
            </div>
            <div class="hero-metrics">
              <div class="hero-metric">
                <div class="label">Market Cap</div>
                <div class="value">${escapeHtml(formatMoney(details.market_cap_usd))}</div>
              </div>
              <div class="hero-metric">
                <div class="label">Liquidity</div>
                <div class="value">${escapeHtml(formatMoney(details.liquidity_usd))}</div>
              </div>
              <div class="hero-metric">
                <div class="label">DEX Age</div>
                <div class="value">${escapeHtml(formatAgeMinutes(row.dexscreener_age_minutes))}</div>
              </div>
            </div>
          </div>
          <div class="hero-side">
            <div>
              <div class="hero-score">${insiderScore(row)}</div>
              <div class="hero-score-label">Insider probability</div>
            </div>
            <div>
              <div style="margin-bottom: 10px;"><span class="badge ${badgeClass(row.final_watchlist_status)}">${escapeHtml(finalDecisionLabel(row.final_watchlist_status))}</span></div>
              <div class="hero-reason">${escapeHtml(row.final_watchlist_reason || "No final reason available")}</div>
            </div>
          </div>
        </div>
      `;
    }

    function renderOpportunityCards(rows) {
      const cards = bestOpportunityRows(rows);
      if (!cards.length) {
        opportunityGridEl.innerHTML = `<article class="opportunity-card"><div class="section-title">No opportunities yet</div><div class="scan-stage" style="margin-top:8px;">Run a scan to populate cards.</div></article>`;
        return;
      }
      opportunityGridEl.innerHTML = cards.map((row) => {
        const details = rowDetails(row);
        return `
          <article class="opportunity-card">
            <div class="card-top">
              <div class="card-token">${renderCardTokenIdentity(row)}</div>
              <span class="badge ${badgeClass(row.final_watchlist_status)}">${escapeHtml(finalDecisionLabel(row.final_watchlist_status))}</span>
            </div>
            <div class="card-stats">
              <div class="mini-stat"><div class="label">Insider</div><div class="value">${insiderScore(row)}/100</div></div>
              <div class="mini-stat"><div class="label">Trap</div><div class="value">${liquidityTrapScore(row)}/100</div></div>
              <div class="mini-stat"><div class="label">Price</div><div class="value">${escapeHtml(formatPrice(row.price_usd))}</div></div>
              <div class="mini-stat"><div class="label">MCap</div><div class="value">${escapeHtml(formatMoney(row.market_cap_usd || details.market_cap_usd))}</div></div>
              <div class="mini-stat"><div class="label">Liquidity</div><div class="value">${escapeHtml(formatLiquidityValue(row, row.liquidity_usd || details.liquidity_usd))}</div></div>
              <div class="mini-stat"><div class="label">Vol 1h</div><div class="value">${escapeHtml(formatMoney(row.volume_1h_usd || details.volume_1h_usd))}</div></div>
            </div>
            <div class="card-footer">
              <span>${escapeHtml(formatAgeMinutes(row.dexscreener_age_minutes))} on DEX</span>
              <a href="${tokenDetailUrl(row)}">Details</a>
            </div>
          </article>
        `;
      }).join("");
    }

    async function copyAddress(address, button) {
      try {
        await navigator.clipboard.writeText(address);
      } catch (error) {
        const textarea = document.createElement("textarea");
        textarea.value = address;
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }
      button.classList.add("copied");
      button.setAttribute("aria-label", "Copied");
      window.setTimeout(() => {
        button.classList.remove("copied");
        button.setAttribute("aria-label", "Copy token address");
      }, 1200);
    }

    function renderSummary(summary) {
      const counts = summary.counts || [];
      const latestRun = summary.latest_run || {};
      const total = counts.reduce((sum, item) => sum + Number(item.count || 0), 0);
      const pass = counts.filter((item) => item.final_watchlist_pass).reduce((sum, item) => sum + Number(item.count || 0), 0);
      const reject = counts.filter((item) => String(item.final_watchlist_status || "").includes("REJECT")).reduce((sum, item) => sum + Number(item.count || 0), 0);
      const wait = counts.filter((item) => String(item.final_watchlist_status || "").includes("WAIT")).reduce((sum, item) => sum + Number(item.count || 0), 0);
      const errors = latestRun.errors_count ?? "0";

      summaryEl.innerHTML = [
        ["Total decisions", total],
        ["Passed", pass],
        ["Rejected", reject],
        ["Latest run", latestRun.id ? `#${latestRun.id}` : "None"],
      ].map(([label, value]) => `
        <article class="metric">
          <div class="label">${escapeHtml(label)}</div>
          <div class="value">${escapeHtml(value)}</div>
        </article>
      `).join("");

      sideStatsEl.innerHTML = [
        ["Unique", summary.unique_tokens ?? total],
        ["Waiting", wait],
        ["Saved", latestRun.tokens_saved ?? "0"],
        ["Errors", errors],
      ].map(([label, value]) => `
        <div class="side-stat">
          <div class="label">${escapeHtml(label)}</div>
          <div class="value">${escapeHtml(value)}</div>
        </div>
      `).join("");
    }

    function renderSkeletonRows(count = 6) {
      // 6 columns to match the watchlist table (Token / Signal / Opp /
      // Liq / Wallet / Decision). Token column gets a two-line skeleton
      // (logo + symbol + name); other columns alternate widths so the
      // table doesn't look like a striped barcode.
      const widths = ["wide", "medium", "wide", "medium", "wide", "short"];
      const tokenCell = `
        <td>
          <div class="skeleton-block medium"></div>
          <div class="skeleton-block short"></div>
        </td>
      `;
      const cellsAfterToken = widths.slice(1).map((w) => `<td><div class="skeleton-block ${w}"></div></td>`).join("");
      const row = `<tr class="skeleton-row" aria-hidden="true">${tokenCell}${cellsAfterToken}</tr>`;
      rowsEl.innerHTML = row.repeat(count);
      tableCountEl.textContent = "Loading…";
    }

    function rowToolbar(row) {
      const address = row.token_address || "";
      if (!address) return "";
      const safeAddress = escapeHtml(address);
      // Solana mainnet links. We don't open a popup ourselves; just
      // hyperlinks that respect cmd/middle-click to open in a new tab.
      const solscan = `https://solscan.io/token/${safeAddress}`;
      const dexscreener = `https://dexscreener.com/solana/${safeAddress}`;
      return `
        <div class="row-toolbar" role="group" aria-label="Quick actions">
          ${starButton(address)}
          <button
            class="copy-button"
            type="button"
            aria-label="Copy token address"
            title="Copy token address"
            data-address="${safeAddress}"
          >${copyIcon()}</button>
          <a
            href="${solscan}"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open on Solscan"
            title="Open on Solscan"
          >SOL</a>
          <a
            href="${dexscreener}"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open on DexScreener"
            title="Open on DexScreener"
          >DEX</a>
        </div>
      `;
    }

    // ---- Signal chain (per-row barcode of the 9 pipeline stages) -------
    //
    // Each row gets a 9-bar barcode showing the tone of every analysis
    // stage. This makes "why" visible without hovering. Stages match the
    // decision drawer order.

    function signalStages(row) {
      const details = rowDetails(row);
      const insiderLevel = details.insider_probability_level || "";
      return [
        { name: "Market",       status: row.market_filter_status,                                          pass: row.market_filter_pass },
        { name: "Contract",     status: row.contract_risk_status,                                          pass: row.contract_risk_pass },
        { name: "Liquidity",    status: details.liquidity_status,                                          pass: null },
        { name: "Liquidity Trap", status: details.liquidity_trap_status,                                    pass: null },
        { name: "Wallet",       status: row.wallet_status,                                                 pass: row.wallet_pass },
        { name: "Cluster",      status: row.cluster_status,                                                pass: row.cluster_pass },
        { name: "Manipulation", status: row.manipulation_status,                                           pass: row.manipulation_pass },
        { name: "Dev",          status: details.dev_audit_status,                                          pass: null },
        { name: "Insider",      status: insiderLevel ? `INSIDER_${insiderLevel}` : "",                     pass: null },
      ];
    }

    function renderSignalChain(row) {
      const stages = signalStages(row);
      const bars = stages.map((stage) => {
        const tone = stageToneFromStatus(stage.status, stage.pass);
        const label = `${stage.name}: ${stage.status || "n/a"}`;
        return `<span class="cb-signal-bar" data-tone="${tone}" title="${escapeHtml(label)}"></span>`;
      }).join("");
      const verdictTone = decisionFinalTone(row);
      const verdictLabel = finalDecisionLabel(row.final_watchlist_status);
      return `
        <div class="cb-signal-cell">
          <div class="cb-signal-chain">${bars}</div>
          <span class="cb-verdict" data-tone="${verdictTone}">${escapeHtml(verdictLabel)}</span>
        </div>
      `;
    }

    // ---- Live header counters ------------------------------------------
    const streamPassCountEl = document.querySelector("#streamPassCount");
    const streamWaitCountEl = document.querySelector("#streamWaitCount");
    const streamRejectCountEl = document.querySelector("#streamRejectCount");
    const streamFreshestEl = document.querySelector("#streamFreshest");

    function updateStreamHeader(rows) {
      let pass = 0, wait = 0, reject = 0, freshest = null;
      rows.forEach((row) => {
        const status = String(row.final_watchlist_status || "");
        if (status === "WATCHLIST_PASS" || status === "WATCHLIST_PASS_HIGH_RISK") pass += 1;
        else if (status.startsWith("WATCHLIST_WAIT") || status === "WATCHLIST_REVIEW") wait += 1;
        else if (status.startsWith("WATCHLIST_REJECT")) reject += 1;
        const ageMin = row.dexscreener_age_minutes ?? row.pair_age_minutes;
        if (ageMin !== null && ageMin !== undefined) {
          const minutes = Number(ageMin);
          if (Number.isFinite(minutes) && (freshest === null || minutes < freshest)) {
            freshest = minutes;
          }
        }
      });
      streamPassCountEl.firstChild.textContent = String(pass);
      streamWaitCountEl.firstChild.textContent = String(wait);
      streamRejectCountEl.firstChild.textContent = String(reject);
      // streamPassCountEl is "<num> PASS" — but textContent above replaces
      // only the leading text node. Ensure full label stays:
      streamPassCountEl.textContent = `${pass} PASS`;
      streamPassCountEl.dataset.tone = "pass";
      streamWaitCountEl.textContent = `${wait} WAIT`;
      streamWaitCountEl.dataset.tone = "wait";
      streamRejectCountEl.textContent = `${reject} REJECT`;
      streamRejectCountEl.dataset.tone = "reject";
      const freshLabel = freshest === null
        ? "—"
        : freshest < 60
          ? `${Math.max(0, Math.round(freshest))}M`
          : freshest < 1440
            ? `${(freshest / 60).toFixed(1)}H`
            : `${(freshest / 1440).toFixed(1)}D`;
      streamFreshestEl.innerHTML = `<b>${escapeHtml(freshLabel)}</b> FRESHEST`;
    }

    function renderRows(rows) {
      tableCountEl.textContent = `${rows.length} TOKENS`;
      if (!rows.length) {
        rowsEl.innerHTML = `<tr><td colspan="6"><div class="cb-stream-empty">No watchlist decisions match the active filters.</div></td></tr>`;
        return;
      }
      rowsEl.innerHTML = rows.map((row) => `
        <tr>
          <td class="token" data-label="Token">${renderTokenIdentity(row)}</td>
          <td class="signal" data-label="Signal Chain">${renderSignalChain(row)}</td>
          <td data-label="Opportunity">${formatTableOpportunity(row)}</td>
          <td data-label="Liquidity">${formatTableLiquidity(row)}</td>
          <td data-label="Wallet">${formatTableWallet(row)}</td>
          <td data-label="Decision">${formatTableDecision(row)}</td>
        </tr>
      `).join("");
    }

    // ---- Tape view (chronological pulse feed) --------------------------
    function renderTape(rows) {
      const tape = document.querySelector("#streamTape");
      if (!rows.length) {
        tape.innerHTML = `<div class="cb-stream-empty">No watchlist decisions match the active filters.</div>`;
        return;
      }
      // Already sorted by sortedRows(); fall back to created_at desc when
      // no explicit sort. Tape cares about chronology — sort by created_at
      // desc so newest is on top.
      const ordered = rows.slice().sort((a, b) => {
        const ta = a.created_at ? Date.parse(a.created_at) : 0;
        const tb = b.created_at ? Date.parse(b.created_at) : 0;
        return tb - ta;
      });
      tape.innerHTML = ordered.map((row) => {
        const symbol = escapeHtml(row.symbol || "Unknown");
        const name = escapeHtml(row.name || "");
        const time = escapeHtml(formatShortDate(row.created_at));
        const verdictTone = decisionFinalTone(row);
        const verdictLabel = finalDecisionLabel(row.final_watchlist_status);
        return `
          <div class="cb-tape-row">
            <div class="cb-tape-time">${time}</div>
            <div class="cb-tape-token">
              <a href="${tokenDetailUrl(row)}">${symbol}</a>
              <span class="sub">${name}</span>
              ${isStarred(row.token_address) ? '<span class="star-mark" aria-label="Starred">★</span>' : ""}
            </div>
            <div class="cb-signal-chain">${signalStages(row).map((stage) => {
              const tone = stageToneFromStatus(stage.status, stage.pass);
              return `<span class="cb-signal-bar" data-tone="${tone}" title="${escapeHtml(stage.name + ': ' + (stage.status || 'n/a'))}"></span>`;
            }).join("")}</div>
            <span class="cb-verdict" data-tone="${verdictTone}">${escapeHtml(verdictLabel)}</span>
          </div>
        `;
      }).join("");
    }

    // ---- Cockpit view (detailed card grid) -----------------------------
    function renderCockpit(rows) {
      const cockpit = document.querySelector("#streamCockpit");
      if (!rows.length) {
        cockpit.innerHTML = `<div class="cb-stream-empty">No watchlist decisions match the active filters.</div>`;
        return;
      }
      cockpit.innerHTML = rows.map((row) => {
        const details = rowDetails(row);
        const symbol = escapeHtml(row.symbol || "Unknown");
        const name = escapeHtml(row.name || "");
        const verdictTone = decisionFinalTone(row);
        const verdictLabel = finalDecisionLabel(row.final_watchlist_status);
        const insider = MemecoUtils.numberOrNull(details.insider_probability_score);
        const trap = MemecoUtils.numberOrNull(details.liquidity_trap_score);
        const liquidity = MemecoUtils.numberOrNull(row.liquidity_usd);
        const reason = escapeHtml(row.final_watchlist_reason || "No reason recorded");
        return `
          <article class="cb-cockpit-card">
            <div class="cb-cockpit-head">
              <div>
                <div class="cb-cockpit-symbol">
                  <a href="${tokenDetailUrl(row)}">${symbol}</a>
                  ${isStarred(row.token_address) ? '<span class="star-mark" aria-label="Starred">★</span>' : ""}
                </div>
                <div class="cb-cockpit-name">${name}</div>
              </div>
              <span class="cb-verdict" data-tone="${verdictTone}">${escapeHtml(verdictLabel)}</span>
            </div>
            <div class="cb-signal-chain">${signalStages(row).map((stage) => {
              const tone = stageToneFromStatus(stage.status, stage.pass);
              return `<span class="cb-signal-bar" data-tone="${tone}" title="${escapeHtml(stage.name + ': ' + (stage.status || 'n/a'))}"></span>`;
            }).join("")}</div>
            <div class="cb-cockpit-stats">
              <div class="cb-cockpit-stat"><div class="lbl">INSIDER</div><div class="val">${insider !== null ? insider + "/100" : "—"}</div></div>
              <div class="cb-cockpit-stat"><div class="lbl">TRAP</div><div class="val">${trap !== null ? trap + "/100" : "—"}</div></div>
              <div class="cb-cockpit-stat"><div class="lbl">LIQ</div><div class="val">${liquidity !== null ? formatMoney(liquidity) : "—"}</div></div>
            </div>
            <div class="cb-cockpit-foot">
              <span title="${reason}">${reason.length > 80 ? reason.slice(0, 80) + "…" : reason}</span>
              <span>${escapeHtml(formatShortDate(row.created_at))}</span>
            </div>
          </article>
        `;
      }).join("");
    }

    // ---- View switcher --------------------------------------------------
    let currentView = "table";
    const viewSwitchEl = document.querySelector(".cb-view-switch");
    const tableWrapEl = document.querySelector(".cb-table-card .table-wrap");
    const tapeEl = document.querySelector("#streamTape");
    const cockpitEl = document.querySelector("#streamCockpit");

    function applyView(view) {
      currentView = view;
      tableWrapEl.hidden = view !== "table";
      tapeEl.hidden = view !== "tape";
      cockpitEl.hidden = view !== "cockpit";
      viewSwitchEl.querySelectorAll(".cb-view-btn").forEach((btn) => {
        const active = btn.dataset.view === view;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-selected", String(active));
      });
      renderActiveView();
    }

    function renderActiveView() {
      const visible = sortedRows(currentRows);
      updateStreamHeader(visible);
      if (currentView === "tape") renderTape(visible);
      else if (currentView === "cockpit") renderCockpit(visible);
      else renderRows(visible);
    }

    viewSwitchEl.addEventListener("click", (event) => {
      const btn = event.target.closest(".cb-view-btn");
      if (!btn) return;
      applyView(btn.dataset.view);
    });

    // ---- Column visibility -------------------------------------------
    //
    // The gear button next to the view switcher opens a small dropdown
    // with one checkbox per togglable pipeline column (Signal / Opp /
    // Liquidity / Wallet). Token and Decision are always visible
    // because they are the sticky anchors. Hidden state lives on the
    // <section class="cb-table-card"> element via `data-hide-<name>="1"`
    // attributes; the CSS selectors above hide the matching col + th +
    // td. Preference persists in localStorage.
    const COLUMN_PREFS_KEY = "memeco.dashboard.columns";
    const COLUMN_KEYS = ["signal", "opportunity", "liquidity", "wallet"];
    const streamCardEl = document.querySelector("#streamCard");
    const colsButtonEl = document.querySelector("#colsButton");
    const colsMenuEl = document.querySelector("#colsMenu");

    function loadColumnPrefs() {
      try {
        const raw = localStorage.getItem(COLUMN_PREFS_KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : {};
      } catch (e) {
        return {};
      }
    }
    function saveColumnPrefs(prefs) {
      try { localStorage.setItem(COLUMN_PREFS_KEY, JSON.stringify(prefs)); }
      catch (e) { /* ignore quota / private mode errors */ }
    }
    function applyColumnPrefs(prefs) {
      COLUMN_KEYS.forEach((key) => {
        const hidden = !!prefs[key];
        if (hidden) streamCardEl.setAttribute(`data-hide-${key}`, "1");
        else streamCardEl.removeAttribute(`data-hide-${key}`);
        const checkbox = colsMenuEl?.querySelector(`input[data-col="${key}"]`);
        if (checkbox) checkbox.checked = !hidden;
      });
    }
    const columnPrefs = loadColumnPrefs();
    applyColumnPrefs(columnPrefs);

    if (colsButtonEl && colsMenuEl) {
      const closeMenu = () => {
        colsMenuEl.hidden = true;
        colsButtonEl.setAttribute("aria-expanded", "false");
      };
      colsButtonEl.addEventListener("click", (event) => {
        event.stopPropagation();
        const open = colsMenuEl.hidden;
        colsMenuEl.hidden = !open;
        colsButtonEl.setAttribute("aria-expanded", String(open));
      });
      colsMenuEl.addEventListener("click", (event) => event.stopPropagation());
      colsMenuEl.addEventListener("change", (event) => {
        const checkbox = event.target.closest("input[data-col]");
        if (!checkbox) return;
        const key = checkbox.dataset.col;
        if (!COLUMN_KEYS.includes(key)) return;
        const hidden = !checkbox.checked;
        if (hidden) columnPrefs[key] = true;
        else delete columnPrefs[key];
        saveColumnPrefs(columnPrefs);
        applyColumnPrefs(columnPrefs);
      });
      // Click anywhere else / ESC closes the menu.
      document.addEventListener("click", (event) => {
        if (colsMenuEl.hidden) return;
        if (event.target.closest("#colsMenu, #colsButton")) return;
        closeMenu();
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !colsMenuEl.hidden) closeMenu();
      });
    }

    function renderDashboardRows(rows, allRows = rows) {
      // Always run diffs against the full unfiltered set so a status
      // change for a token currently filtered-out is still recorded
      // and surfaces when the filter is cleared.
      recordDecisionDiffs(allRows);
      const opportunities = allRows.filter((row) => row.final_watchlist_pass || String(row.final_watchlist_status || "").includes("PASS"));
      const risks = allRows.filter((row) => String(row.final_watchlist_status || "").includes("REJECT"));
      sideOpportunityCountEl.textContent = String(opportunities.length);
      sideRiskCountEl.textContent = String(risks.length);
      renderHero(allRows);
      renderOpportunityCards(allRows);
      const filtered = starredOnly
        ? rows.filter((row) => isStarred(row.token_address))
        : rows;
      currentRows = filtered;
      renderActiveView();
    }

    function elapsedMinutes(startedAt) {
      if (!startedAt) return 0;
      const started = new Date(startedAt).getTime();
      if (Number.isNaN(started)) return 0;
      return Math.max(0, (Date.now() - started) / 60000);
    }

    function systemLoadFromScan(state) {
      const steps = Array.isArray(state.steps) ? state.steps : [];
      const runningSteps = steps.filter((step) => step.status === "running").length;
      const doneSteps = steps.filter((step) => step.status === "done").length;
      const errorSteps = steps.filter((step) => String(step.status || "").includes("error")).length;
      let load = 8;

      if (state.error || state.status === "failed" || errorSteps) {
        load = 95;
      } else if (state.running) {
        load = 38
          + Math.min(22, doneSteps * 3)
          + Math.min(16, runningSteps * 8)
          + Math.min(18, elapsedMinutes(state.started_at) * 3);
      } else if (state.status === "finished") {
        load = 18;
      }

      load = Math.max(0, Math.min(100, Math.round(load)));

      if (load >= 75) {
        return {
          load,
          tone: "heavy",
          label: state.error ? "Problem" : "Heavy",
          hint: state.error
            ? "A scan problem was detected. Check the error below."
            : "The analysis pipeline is busy. Wait before starting another action.",
        };
      }

      if (load >= 40) {
        return {
          load,
          tone: "medium",
          label: "Active",
          hint: "A scan is running. Dashboard reads are fine, but analysis is using more work.",
        };
      }

      return {
        load,
        tone: "light",
        label: "Light",
        hint: state.status === "finished"
          ? "Last scan finished. System is back to light dashboard work."
          : "No active scan. Dashboard is only reading cached results.",
      };
    }

    function renderSystemLoad(state) {
      const meter = systemLoadFromScan(state);
      const degrees = Math.round(meter.load * 1.8);
      systemLoadMeterEl.className = `system-load ${meter.tone}`;
      loadGaugeEl.style.setProperty("--load-deg", `${degrees}deg`);
      loadValueEl.textContent = `${meter.load}%`;
      loadStatusEl.textContent = meter.label;
      loadHintEl.textContent = meter.hint;
    }

    // ---- Decision diff (status flip badges) ----------------------------
    //
    // When a token's final_watchlist_status changes between two
    // consecutive renders, we render a small "↑ now PASS" / "↓ was PASS"
    // badge for ~30s in the Decision column. Keeps users aware of
    // movement during a live scan without forcing a full re-read.

    const FLIP_TTL_MS = 30_000;
    const lastSeenStatus = new Map();   // address -> { status, ts }
    const activeFlips = new Map();      // address -> { from, to, ts }

    function rankDecision(status) {
      // Same ordinal as the sort: higher = better.
      const value = String(status || "");
      if (value === "WATCHLIST_PASS") return 5;
      if (value === "WATCHLIST_PASS_HIGH_RISK") return 4;
      if (value === "WATCHLIST_REVIEW") return 3;
      if (value.startsWith("WATCHLIST_WAIT")) return 2;
      if (value.startsWith("WATCHLIST_REJECT")) return 1;
      return 0;
    }

    function recordDecisionDiffs(rows) {
      const now = Date.now();
      // Mark anything that changed since last we saw it.
      rows.forEach((row) => {
        const addr = row.token_address;
        if (!addr) return;
        const status = String(row.final_watchlist_status || "");
        const prev = lastSeenStatus.get(addr);
        if (prev && prev.status && prev.status !== status) {
          activeFlips.set(addr, { from: prev.status, to: status, ts: now });
          // Browser notification for starred tokens — gated on the
          // user's localStorage opt-in. Skip on the very first render
          // (when prev.ts is older than 30 min, the flip is most
          // likely a re-warm rather than a real change).
          if (isStarred(addr) && (now - (prev.ts || 0) < FLIP_TTL_MS * 8)) {
            maybeNotifyStarFlip(row, prev.status, status);
          }
        }
        lastSeenStatus.set(addr, { status, ts: now });
      });
      // Drop expired flips so the next render doesn't show stale badges.
      for (const [addr, flip] of activeFlips) {
        if (now - flip.ts > FLIP_TTL_MS) activeFlips.delete(addr);
      }
      // Drop stale "lastSeen" entries after 30 minutes so we don't false-
      // alarm a token reappearing in the watchlist after a long absence.
      const STALE_MS = 30 * 60 * 1000;
      for (const [addr, info] of lastSeenStatus) {
        if (now - info.ts > STALE_MS) lastSeenStatus.delete(addr);
      }
    }

    // ---- Browser notifications for starred-token status flips ---------
    //
    // Pure-frontend feature. When a starred token's
    // final_watchlist_status changes between two consecutive renders we
    // fire a Notification (if the user has granted permission). The opt-
    // in is one-time and stored in localStorage; nobody gets prompted
    // out of the blue.

    const NOTIFY_OPT_KEY = "memeco.notify.starred";

    function ensureNotifyPermission() {
      if (typeof Notification === "undefined") return Promise.resolve("unsupported");
      if (Notification.permission === "granted") return Promise.resolve("granted");
      if (Notification.permission === "denied")  return Promise.resolve("denied");
      return Notification.requestPermission();
    }

    function notifyEnabled() {
      try { return localStorage.getItem(NOTIFY_OPT_KEY) === "on"; } catch (e) { return false; }
    }

    function setNotifyEnabled(on) {
      try { localStorage.setItem(NOTIFY_OPT_KEY, on ? "on" : "off"); } catch (e) {}
    }

    function maybeNotifyStarFlip(row, fromStatus, toStatus) {
      if (!notifyEnabled()) return;
      if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
      const dir = rankDecision(toStatus) > rankDecision(fromStatus) ? "↑" : "↓";
      const symbol = row.symbol || row.name || (row.token_address || "").slice(0, 6);
      try {
        new Notification(`★ ${symbol}: ${dir} ${finalDecisionLabel(toStatus)}`, {
          body: `Was ${finalDecisionLabel(fromStatus)} · ${row.final_watchlist_reason || "Status changed"}`,
          tag: `memeco-flip-${row.token_address}`,
          icon: row.logo_url || undefined,
        });
      } catch (e) { /* no-op */ }
    }

    // Star toggle UI piggybacks here: the first time a user stars a
    // token we ask for Notification permission. They can disable later
    // via the cheat-sheet (or the dev console: localStorage.setItem(
    // 'memeco.notify.starred', 'off')).
    async function promptNotifyOnFirstStar() {
      if (notifyEnabled()) return;
      const permission = await ensureNotifyPermission();
      if (permission === "granted") setNotifyEnabled(true);
    }

    function decisionFlipBadge(row) {
      const flip = activeFlips.get(row.token_address);
      if (!flip) return "";
      const direction =
        rankDecision(flip.to) > rankDecision(flip.from)
          ? "up"
          : rankDecision(flip.to) < rankDecision(flip.from)
            ? "down"
            : "side";
      const arrow = direction === "up" ? "↑" : direction === "down" ? "↓" : "↻";
      const label = `${arrow} now ${finalDecisionLabel(flip.to)}`;
      return `<span class="decision-flip ${direction}" title="Was ${escapeHtml(finalDecisionLabel(flip.from))}">${escapeHtml(label)}</span>`;
    }

    // ---- Starred tokens (local) -----------------------------------------
    //
    // Persisted in localStorage. Pure client-side concern -- no backend
    // change. Star toggles live in the row toolbar; a "Starred" filter
    // chip narrows the table to favorites only.

    const STARRED_KEY = "memeco.starred";
    const starred = new Set();

    function loadStarred() {
      try {
        const raw = localStorage.getItem(STARRED_KEY);
        if (!raw) return;
        const list = JSON.parse(raw);
        if (Array.isArray(list)) {
          list.forEach((addr) => {
            if (typeof addr === "string" && addr) starred.add(addr);
          });
        }
      } catch (error) {
        // localStorage unavailable / corrupted -- silent.
      }
    }

    function saveStarred() {
      try {
        localStorage.setItem(STARRED_KEY, JSON.stringify(Array.from(starred)));
      } catch (error) {
        // ignore
      }
    }

    function isStarred(address) {
      return Boolean(address) && starred.has(address);
    }

    function toggleStar(address) {
      if (!address) return;
      if (starred.has(address)) {
        starred.delete(address);
      } else {
        starred.add(address);
        // First time the user stars something we offer to enable
        // notifications for status flips. Future stars are silent
        // because the opt-in is sticky.
        promptNotifyOnFirstStar();
      }
      saveStarred();
      // Re-render so star markers, toolbar buttons, and the optional
      // "Starred" filter all reflect the change.
      renderActiveView();
    }

    // Cross-tab sync: another tab toggling a star updates this tab too.
    window.addEventListener("storage", (event) => {
      if (event.key !== STARRED_KEY) return;
      starred.clear();
      try {
        const list = JSON.parse(event.newValue || "[]");
        if (Array.isArray(list)) list.forEach((a) => typeof a === "string" && starred.add(a));
      } catch (error) {
        // ignore
      }
      renderActiveView();
    });

    loadStarred();

    function starButton(address) {
      const safe = escapeHtml(address || "");
      const pressed = isStarred(address);
      return `
        <button
          class="star-button"
          type="button"
          data-star-address="${safe}"
          aria-pressed="${pressed}"
          aria-label="${pressed ? "Unstar token" : "Star token"}"
          title="${pressed ? "Unstar token" : "Star token (saves locally)"}"
        >${pressed ? "★" : "☆"}</button>
      `;
    }

    // Click delegate for star buttons. Lives at document level so it
    // works for buttons rendered later (auto-refresh).
    document.addEventListener("click", (event) => {
      const btn = event.target.closest(".star-button");
      if (!btn) return;
      event.preventDefault();
      event.stopPropagation();
      toggleStar(btn.dataset.starAddress || "");
    });

    // ---- Decision tree drawer -------------------------------------------
    //
    // Hovering any watchlist row opens a slide-in drawer on the right with
    // the full decision tree (Market -> Contract -> Liquidity -> Wallet
    // -> Cluster -> Manipulation -> Final). The data already lives on the
    // row -- no extra request. Pin button keeps the drawer visible while
    // the user hovers other rows.

    const drawerEl = document.querySelector("#decisionDrawer");
    let drawerHoverTimer = null;
    let drawerHideTimer = null;
    let drawerPinned = false;
    let drawerCurrentRow = null;

    const STAGE_TONE = {
      pass: "pass",
      warn: "warn",
      fail: "fail",
      unknown: "unknown",
    };

    function stageToneFromStatus(status, passFlag) {
      const value = String(status || "").toUpperCase();
      if (value.includes("DANGER") || value.includes("REJECT") || value.includes("CRITICAL")) {
        return STAGE_TONE.fail;
      }
      if (value.includes("WARNING") || value.includes("HIGH")) return STAGE_TONE.warn;
      if (value.includes("UNKNOWN") || value.includes("WAIT") || value.includes("REVIEW")) {
        return STAGE_TONE.unknown;
      }
      if (value.includes("PASS") || value.includes("STRONG") || value.includes("MODERATE")) {
        return STAGE_TONE.pass;
      }
      if (passFlag === true) return STAGE_TONE.pass;
      if (passFlag === false) return STAGE_TONE.fail;
      return STAGE_TONE.unknown;
    }

    function decisionFinalTone(row) {
      const status = String(row.final_watchlist_status || "");
      if (status === "WATCHLIST_PASS") return "pass";
      if (status === "WATCHLIST_PASS_HIGH_RISK") return "warn";
      if (status.startsWith("WATCHLIST_REJECT")) return "fail";
      if (status === "WATCHLIST_REVIEW") return "review";
      return "unknown";
    }

    function renderStep(name, status, detail, score) {
      const tone = stageToneFromStatus(status);
      const detailHtml = detail ? `<div class="step-detail">${escapeHtml(detail)}</div>` : "";
      const scoreHtml = score !== undefined && score !== null
        ? `<div class="step-score">${escapeHtml(score)}</div>`
        : `<div class="step-score"></div>`;
      return `
        <div class="decision-step ${tone}">
          <span class="dot" aria-hidden="true"></span>
          <div>
            <div class="step-name">${escapeHtml(name)}</div>
            ${detailHtml}
          </div>
          ${scoreHtml}
        </div>
      `;
    }

    function renderDrawer(row) {
      drawerCurrentRow = row;
      const details = rowDetails(row);
      const symbol = row.symbol || row.name || row.token_address || "Token";
      const finalTone = decisionFinalTone(row);
      const finalLabel = finalDecisionLabel(row.final_watchlist_status);
      const finalReason = row.final_watchlist_reason || "";

      const insider = MemecoUtils.numberOrNull(details.insider_probability_score);
      const insiderLevel = details.insider_probability_level || "";
      const trapStatus = details.liquidity_trap_status || "";
      const trapScore = MemecoUtils.numberOrNull(details.liquidity_trap_score);
      const liquidityUsd = row.liquidity_usd ?? details.liquidity_usd;
      const tokenLink = tokenDetailUrl(row);

      drawerEl.innerHTML = `
        <header>
          <div>
            <div class="drawer-title">Decision</div>
            <div class="drawer-symbol" id="drawerSymbol">${escapeHtml(symbol)}</div>
          </div>
          <div class="drawer-controls">
            <button
              type="button"
              class="drawer-pin ${drawerPinned ? "pinned" : ""}"
              aria-pressed="${drawerPinned}"
              aria-label="${drawerPinned ? "Unpin drawer" : "Pin drawer"}"
              title="${drawerPinned ? "Unpin drawer" : "Pin drawer"}"
            >📌</button>
            <button
              type="button"
              class="drawer-close"
              aria-label="Close drawer"
              title="Close drawer"
            >✕</button>
          </div>
        </header>
        <div class="decision-tree">
          ${renderStep("Market", row.market_filter_status, "", row.market_warning_level || "")}
          ${renderStep(
            "Contract",
            row.contract_risk_status,
            "",
            row.risk_score !== null && row.risk_score !== undefined ? `${row.risk_score}/10` : ""
          )}
          ${renderStep(
            "Liquidity",
            details.liquidity_status,
            liquidityUsd ? formatMoney(liquidityUsd) : "",
            ""
          )}
          ${renderStep(
            "Liquidity Trap",
            trapStatus,
            "",
            trapScore !== null ? `${trapScore}/100` : ""
          )}
          ${renderStep(
            "Wallet Concentration",
            row.wallet_status,
            "",
            row.top_holder_percent !== null && row.top_holder_percent !== undefined
              ? `top ${row.top_holder_percent}%`
              : ""
          )}
          ${renderStep("Cluster", row.cluster_status, "",
            row.largest_cluster_size ? `${row.largest_cluster_size} wallets` : ""
          )}
          ${renderStep("Manipulation", row.manipulation_status, "",
            row.manipulation_score !== null && row.manipulation_score !== undefined
              ? `${row.manipulation_score}/10`
              : ""
          )}
          ${renderStep(
            "Dev Audit",
            details.dev_audit_status,
            "",
            ""
          )}
          ${renderStep(
            "Insider Probability",
            insiderLevel ? `INSIDER_${insiderLevel}` : "",
            insider !== null ? `${insider}/100` : "",
            ""
          )}
        </div>
        <div class="decision-final ${finalTone}">
          <div class="label">Final decision</div>
          <div class="value">${escapeHtml(finalLabel)}</div>
          ${finalReason ? `<div class="reason">${escapeHtml(finalReason)}</div>` : ""}
        </div>
        <a class="open-detail" href="${tokenLink}">Open token detail →</a>
      `;
    }

    function showDrawer(row) {
      renderDrawer(row);
      drawerEl.classList.add("is-visible");
      drawerEl.setAttribute("aria-hidden", "false");
    }

    function hideDrawer() {
      if (drawerPinned) return;
      drawerEl.classList.remove("is-visible");
      drawerEl.setAttribute("aria-hidden", "true");
      drawerCurrentRow = null;
    }

    function rowFromEvent(event) {
      const tr = event.target.closest("tbody tr");
      if (!tr || tr.classList.contains("skeleton-row")) return null;
      const index = Array.from(rowsEl.children).indexOf(tr);
      if (index < 0) return null;
      // The visible rows are sortedRows(currentRows); honor that ordering.
      const visible = sortedRows(currentRows);
      return visible[index] || null;
    }

    rowsEl.addEventListener("mouseover", (event) => {
      // Don't open while interacting with the toolbar — clicking SOL/DEX
      // should not be interrupted by a drawer reflow.
      if (event.target.closest(".row-toolbar")) return;
      const row = rowFromEvent(event);
      if (!row) return;
      if (drawerHideTimer) {
        clearTimeout(drawerHideTimer);
        drawerHideTimer = null;
      }
      if (drawerHoverTimer) clearTimeout(drawerHoverTimer);
      drawerHoverTimer = setTimeout(() => showDrawer(row), 220);
    });

    rowsEl.addEventListener("mouseleave", () => {
      if (drawerHoverTimer) clearTimeout(drawerHoverTimer);
      drawerHoverTimer = null;
      if (drawerPinned) return;
      // Grace period -- so moving the cursor onto the drawer keeps it open.
      drawerHideTimer = setTimeout(hideDrawer, 240);
    });

    drawerEl.addEventListener("mouseenter", () => {
      if (drawerHideTimer) {
        clearTimeout(drawerHideTimer);
        drawerHideTimer = null;
      }
    });

    drawerEl.addEventListener("mouseleave", () => {
      if (drawerPinned) return;
      drawerHideTimer = setTimeout(hideDrawer, 200);
    });

    drawerEl.addEventListener("click", (event) => {
      const closeBtn = event.target.closest(".drawer-close");
      if (closeBtn) {
        drawerPinned = false;
        hideDrawer();
        return;
      }
      const pinBtn = event.target.closest(".drawer-pin");
      if (pinBtn) {
        drawerPinned = !drawerPinned;
        if (drawerCurrentRow) renderDrawer(drawerCurrentRow);
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && drawerEl.classList.contains("is-visible")) {
        drawerPinned = false;
        hideDrawer();
      }
    });

    // ---- Keyboard navigation -------------------------------------------
    //
    // Power-user shortcuts. All keys are ignored when the user is typing
    // in an input/textarea/contenteditable, so they never fight with the
    // manual-analyze field or the URL bar.
    //
    //   /                focus the manual-analyze input
    //   j or ArrowDown   highlight next row
    //   k or ArrowUp     highlight previous row
    //   Enter            open the highlighted row's token detail
    //   c                copy the highlighted token's address
    //   ?                toggle the shortcuts cheat-sheet overlay
    //   Esc              close drawer / overlay / blur input

    let highlightedIndex = -1;

    function isTypingTarget(target) {
      if (!target) return false;
      const tag = target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
      if (target.isContentEditable) return true;
      return false;
    }

    function visibleRows() {
      return Array.from(rowsEl.querySelectorAll("tr")).filter(
        (tr) => !tr.classList.contains("skeleton-row") && !tr.querySelector(".empty"),
      );
    }

    function setHighlight(index) {
      const trs = visibleRows();
      if (!trs.length) {
        highlightedIndex = -1;
        return;
      }
      // Wrap-around so j past the bottom goes to the top, k past the
      // top goes to the bottom. Feels like vim, terminal mail clients,
      // gmail.
      const next = ((index % trs.length) + trs.length) % trs.length;
      trs.forEach((tr, i) => tr.classList.toggle("kbd-active", i === next));
      highlightedIndex = next;
      const tr = trs[next];
      // scrollIntoView with block:nearest avoids jumpy scrolling when
      // the highlighted row is already visible.
      tr.scrollIntoView({ block: "nearest", behavior: "smooth" });

      // Open the decision drawer for the highlighted row -- gives
      // keyboard users the same context that mouse hover provides.
      const visible = sortedRows(currentRows);
      const row = visible[next];
      if (row) {
        // Skip the hover delay for keyboard nav; show immediately.
        if (drawerHoverTimer) clearTimeout(drawerHoverTimer);
        if (drawerHideTimer) clearTimeout(drawerHideTimer);
        showDrawer(row);
      }
    }

    function clearHighlight() {
      visibleRows().forEach((tr) => tr.classList.remove("kbd-active"));
      highlightedIndex = -1;
    }

    function highlightedRow() {
      if (highlightedIndex < 0) return null;
      const visible = sortedRows(currentRows);
      return visible[highlightedIndex] || null;
    }

    function openHighlightedRow() {
      const row = highlightedRow();
      if (!row) return;
      const url = tokenDetailUrl(row);
      window.location.href = url;
    }

    function copyHighlightedAddress() {
      const row = highlightedRow();
      if (!row || !row.token_address) return;
      // Reuse the existing copy delegate by faking a click on a hidden
      // copy-button-shaped element; simpler to just use the helper.
      copyAddress(row.token_address, null);
    }

    // Cheat-sheet overlay built lazily on first ? press.
    let cheatsheetEl = null;

    function buildCheatsheet() {
      const el = document.createElement("div");
      el.className = "kbd-cheatsheet";
      el.setAttribute("role", "dialog");
      el.setAttribute("aria-label", "Keyboard shortcuts");
      el.innerHTML = `
        <div class="kbd-cheatsheet-card">
          <div class="kbd-cheatsheet-title">Keyboard shortcuts</div>
          <dl>
            <dt><kbd>/</kbd></dt><dd>Focus manual analyze</dd>
            <dt><kbd>j</kbd> / <kbd>↓</kbd></dt><dd>Next row</dd>
            <dt><kbd>k</kbd> / <kbd>↑</kbd></dt><dd>Previous row</dd>
            <dt><kbd>Enter</kbd></dt><dd>Open token detail</dd>
            <dt><kbd>c</kbd></dt><dd>Copy address</dd>
            <dt><kbd>?</kbd></dt><dd>Toggle this overlay</dd>
            <dt><kbd>Esc</kbd></dt><dd>Close drawer / overlay</dd>
          </dl>
          <div class="kbd-cheatsheet-hint">Press <kbd>Esc</kbd> or <kbd>?</kbd> to close.</div>
        </div>
      `;
      el.addEventListener("click", (event) => {
        if (event.target === el) toggleCheatsheet(false);
      });
      document.body.appendChild(el);
      return el;
    }

    function toggleCheatsheet(force) {
      if (!cheatsheetEl) cheatsheetEl = buildCheatsheet();
      const next = typeof force === "boolean" ? force : !cheatsheetEl.classList.contains("is-visible");
      cheatsheetEl.classList.toggle("is-visible", next);
    }

    document.addEventListener("keydown", (event) => {
      // Inputs always own their keystrokes.
      if (isTypingTarget(event.target)) {
        if (event.key === "Escape") event.target.blur();
        return;
      }
      // Don't hijack browser shortcuts.
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      switch (event.key) {
        case "/":
          event.preventDefault();
          if (manualTokenInputEl) {
            manualTokenInputEl.focus();
            manualTokenInputEl.select();
          }
          break;
        case "j":
        case "ArrowDown":
          event.preventDefault();
          setHighlight(highlightedIndex + 1);
          break;
        case "k":
        case "ArrowUp":
          event.preventDefault();
          setHighlight(highlightedIndex < 0 ? 0 : highlightedIndex - 1);
          break;
        case "Enter":
          if (highlightedIndex >= 0) {
            event.preventDefault();
            openHighlightedRow();
          }
          break;
        case "c":
          if (highlightedIndex >= 0) {
            event.preventDefault();
            copyHighlightedAddress();
          }
          break;
        case "?":
          event.preventDefault();
          toggleCheatsheet();
          break;
        case "Escape":
          if (cheatsheetEl && cheatsheetEl.classList.contains("is-visible")) {
            toggleCheatsheet(false);
            event.preventDefault();
          } else if (highlightedIndex >= 0) {
            clearHighlight();
            event.preventDefault();
          }
          break;
      }
    });

    // Keep highlight valid when rows re-render (auto-refresh / sort / filter).
    // If the previously-highlighted row is no longer present, clear.
    const tableObserver = new MutationObserver(() => {
      if (highlightedIndex < 0) return;
      const trs = visibleRows();
      if (!trs.length || highlightedIndex >= trs.length) {
        clearHighlight();
      } else {
        trs.forEach((tr, i) => tr.classList.toggle("kbd-active", i === highlightedIndex));
      }
    });
    tableObserver.observe(rowsEl, { childList: true });

    // ---- Status filter chips --------------------------------------------
    //
    // The decision filter is a multi-select chip group. Internal state is a
    // Set of statuses; an empty set means "all decisions" (the "All" chip
    // is then visually active). The legacy `?status=A` URL form still works
    // and is read as a single-element selection.

    const statusFilterEl = document.querySelector("#statusFilter");
    const activeStatuses = new Set();
    let starredOnly = false;

    function getStatusParam() {
      // Comma-separated for the API: "A,B,C". Empty when nothing selected.
      return Array.from(activeStatuses).join(",");
    }

    function renderStatusChips() {
      const chips = statusFilterEl.querySelectorAll(".filter-chip");
      const allEmpty = activeStatuses.size === 0 && !starredOnly;
      chips.forEach((chip) => {
        const value = chip.dataset.status || "";
        const localFilter = chip.dataset.filter || "";
        let pressed;
        if (localFilter === "starred") {
          pressed = starredOnly;
        } else if (value) {
          pressed = activeStatuses.has(value);
        } else {
          pressed = allEmpty;
        }
        chip.setAttribute("aria-pressed", String(pressed));
      });
    }

    function setActiveStatuses(list) {
      activeStatuses.clear();
      list.forEach((s) => {
        if (s) activeStatuses.add(s);
      });
      renderStatusChips();
    }

    function toggleStatus(value, localFilter) {
      if (localFilter === "starred") {
        starredOnly = !starredOnly;
      } else if (!value) {
        // "All decisions" chip: clear everything (status + starred).
        activeStatuses.clear();
        starredOnly = false;
      } else if (activeStatuses.has(value)) {
        activeStatuses.delete(value);
      } else {
        activeStatuses.add(value);
      }
      renderStatusChips();
      writeUrlState();
      loadDashboard();
    }

    statusFilterEl.addEventListener("click", (event) => {
      const chip = event.target.closest(".filter-chip");
      if (!chip || !statusFilterEl.contains(chip)) return;
      toggleStatus(chip.dataset.status || "", chip.dataset.filter || "");
    });

    // ---- Density toggle -------------------------------------------------
    //
    // Compact mode shrinks rows ~40% so power users can scan more tokens
    // at once. Preference persists in localStorage. Pure CSS swap; no
    // re-render required.

    const DENSITY_KEY = "memeco.dashboard.density";
    const densityToggleEl = document.querySelector("#densityToggle");

    function applyDensity(mode) {
      const compact = mode === "compact";
      document.body.classList.toggle("density-compact", compact);
      if (densityToggleEl) {
        densityToggleEl.setAttribute("aria-pressed", String(compact));
        densityToggleEl.textContent = compact ? "Comfy" : "Compact";
      }
    }

    function loadDensity() {
      try {
        return localStorage.getItem(DENSITY_KEY) || "comfy";
      } catch (error) {
        return "comfy";
      }
    }

    function saveDensity(mode) {
      try {
        localStorage.setItem(DENSITY_KEY, mode);
      } catch (error) {
        // localStorage unavailable -- silent.
      }
    }

    applyDensity(loadDensity());

    if (densityToggleEl) {
      densityToggleEl.addEventListener("click", () => {
        const next = loadDensity() === "compact" ? "comfy" : "compact";
        saveDensity(next);
        applyDensity(next);
      });
    }

    // ---- Table sorting --------------------------------------------------
    //
    // Headers cycle: unsorted → descending → ascending → unsorted (back to
    // backend's natural "latest first" order). All sorting is client-side
    // over the rows already on the page; no extra requests.

    let currentRows = [];
    let currentSort = { key: null, dir: null };

    const SORT_EXTRACTORS = {
      symbol: (row) => String(row.symbol || row.name || row.token_address || "").toLowerCase(),
      opportunity: (row) => {
        // Lower insider probability is better → invert so descending means
        // "best opportunities first."
        const details = MemecoUtils.parseDetails(row.details);
        const insider = MemecoUtils.numberOrNull(details.insider_probability_score);
        return insider === null ? null : -insider;
      },
      safety: (row) => {
        // Lower risk score = safer → invert so descending = "safest first."
        const score = MemecoUtils.numberOrNull(row.risk_score);
        return score === null ? null : -score;
      },
      liquidity: (row) => MemecoUtils.numberOrNull(row.liquidity_usd),
      manipulation: (row) => {
        // Lower manipulation = cleaner → invert.
        const score = MemecoUtils.numberOrNull(row.manipulation_score);
        return score === null ? null : -score;
      },
      decision: (row) => {
        // Pass > High Risk > Review > Wait > Reject. Map to a sortable
        // ordinal so "descending" surfaces the cleanest decisions first.
        const status = String(row.final_watchlist_status || "");
        if (status === "WATCHLIST_PASS") return 5;
        if (status === "WATCHLIST_PASS_HIGH_RISK") return 4;
        if (status === "WATCHLIST_REVIEW") return 3;
        if (status.startsWith("WATCHLIST_WAIT")) return 2;
        if (status.startsWith("WATCHLIST_REJECT")) return 1;
        return 0;
      },
      updated: (row) => {
        const ts = row.created_at ? Date.parse(row.created_at) : NaN;
        return Number.isFinite(ts) ? ts : null;
      },
    };

    function sortedRows(rows) {
      if (!currentSort.key || !currentSort.dir) return rows;
      const extractor = SORT_EXTRACTORS[currentSort.key];
      if (!extractor) return rows;
      const dir = currentSort.dir === "asc" ? 1 : -1;
      // Stable sort: copy first.
      return rows.slice().sort((a, b) => {
        const va = extractor(a);
        const vb = extractor(b);
        // Nulls always sink to the bottom regardless of direction.
        if (va === null && vb === null) return 0;
        if (va === null) return 1;
        if (vb === null) return -1;
        if (va < vb) return -1 * dir;
        if (va > vb) return 1 * dir;
        return 0;
      });
    }

    function updateSortHeaders() {
      document.querySelectorAll("th.sortable").forEach((th) => {
        const key = th.dataset.sortKey;
        if (!currentSort.dir || currentSort.key !== key) {
          th.removeAttribute("aria-sort");
          th.querySelector(".sort-arrow").textContent = "↕";
          return;
        }
        th.setAttribute("aria-sort", currentSort.dir === "asc" ? "ascending" : "descending");
        th.querySelector(".sort-arrow").textContent = currentSort.dir === "asc" ? "↑" : "↓";
      });
    }

    function setSort(key) {
      if (currentSort.key !== key) {
        currentSort = { key, dir: "desc" };
      } else if (currentSort.dir === "desc") {
        currentSort = { key, dir: "asc" };
      } else {
        currentSort = { key: null, dir: null };
      }
      updateSortHeaders();
      writeUrlState();
      renderActiveView();
    }

    document.querySelectorAll("th.sortable").forEach((th) => {
      th.addEventListener("click", () => setSort(th.dataset.sortKey));
    });
    //
    // Persist the visible decision filter in the URL so users can bookmark
    // a specific view ("?status=WATCHLIST_PASS") and share it. Future
    // additions (sort column, density, …) can extend writeUrlState/
    // readUrlState without touching call sites.

    function readUrlState() {
      try {
        const params = new URLSearchParams(window.location.search);
        return {
          status: params.get("status") || "",
          sort: params.get("sort") || "",
          dir: params.get("dir") || "",
          starred: params.get("starred") === "1",
        };
      } catch (error) {
        return { status: "", sort: "", dir: "", starred: false };
      }
    }

    function writeUrlState() {
      try {
        const params = new URLSearchParams(window.location.search);
        const status = getStatusParam();
        if (status) params.set("status", status); else params.delete("status");
        if (currentSort.key && currentSort.dir) {
          params.set("sort", currentSort.key);
          params.set("dir", currentSort.dir);
        } else {
          params.delete("sort");
          params.delete("dir");
        }
        if (starredOnly) params.set("starred", "1"); else params.delete("starred");
        const query = params.toString();
        const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
        window.history.replaceState(null, "", next);
      } catch (error) {
        // Older browsers / file:// fallthrough; silently ignored.
      }
    }

    function applyUrlState() {
      const { status, sort, dir, starred } = readUrlState();
      if (status) {
        const known = new Set(
          Array.from(statusFilterEl.querySelectorAll(".filter-chip"))
            .map((chip) => chip.dataset.status || "")
            .filter(Boolean)
        );
        const requested = status.split(",").map((s) => s.trim()).filter(Boolean);
        setActiveStatuses(requested.filter((s) => known.has(s)));
      } else {
        setActiveStatuses([]);
      }
      starredOnly = Boolean(starred);
      renderStatusChips();
      if (
        sort && SORT_EXTRACTORS[sort]
        && (dir === "asc" || dir === "desc")
      ) {
        currentSort = { key: sort, dir };
        updateSortHeaders();
      }
    }

    applyUrlState();

    // ---- Live freshness + auto-refresh ----------------------------------
    //
    // The dashboard polls /api/watchlist on a fixed interval and shows a
    // "Updated Xs ago" tick beside a pulsing dot. The poll pauses when the
    // tab is hidden (avoids hammering Helius/DexScreener for nothing) and
    // resumes immediately when it becomes visible again.

    const WATCHLIST_REFRESH_MS = 20_000;
    let lastWatchlistAt = null;
    let watchlistTimer = null;
    let watchlistInFlight = false;
    let firstWatchlistLoad = true;
    let freshnessTimer = null;

    function setFreshness(text, dotState = "live") {
      freshnessEl.textContent = text;
      liveDotEl.className = `live-dot ${dotState}`;
      const titles = {
        live: "Live updates: on",
        paused: "Live updates paused (tab hidden)",
        error: "Last update failed",
      };
      liveDotEl.title = titles[dotState] || "";
    }

    function tickFreshness() {
      if (!lastWatchlistAt) return;
      const seconds = Math.max(0, Math.floor((Date.now() - lastWatchlistAt) / 1000));
      const label = seconds < 60
        ? `Updated ${seconds}s ago`
        : seconds < 3600
          ? `Updated ${Math.floor(seconds / 60)}m ago`
          : `Updated ${Math.floor(seconds / 3600)}h ago`;
      const state = document.hidden ? "paused" : "live";
      setFreshness(label, state);
    }

    function scheduleNextRefresh() {
      if (watchlistTimer) clearTimeout(watchlistTimer);
      if (document.hidden) return;
      watchlistTimer = setTimeout(loadDashboard, WATCHLIST_REFRESH_MS);
    }

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        if (watchlistTimer) clearTimeout(watchlistTimer);
        watchlistTimer = null;
        setFreshness("Paused", "paused");
        return;
      }
      // Returning to the tab: refresh immediately.
      tickFreshness();
      loadDashboard();
    });

    async function loadDashboard() {
      if (watchlistInFlight) return;          // never overlap requests
      if (watchlistTimer) clearTimeout(watchlistTimer);
      watchlistInFlight = true;

      // Show skeleton placeholders only when the table is empty (first
      // load, or a previous error wiped it). Auto-refreshes keep the
      // existing rows visible so they don't visually thrash.
      if (firstWatchlistLoad) {
        renderSkeletonRows();
      }

      const status = getStatusParam();
      const statusParam = status ? `&status=${encodeURIComponent(status)}` : "";
      try {
        const [summaryResponse, watchlistResponse] = await Promise.all([
          fetch("/api/summary"),
          fetch(`/api/watchlist?limit=100${statusParam}`),
        ]);
        if (!summaryResponse.ok || !watchlistResponse.ok) {
          throw new Error("Request failed");
        }
        const summary = await summaryResponse.json();
        const rows = await watchlistResponse.json();
        let allRows = rows;
        if (status) {
          const allWatchlistResponse = await fetch("/api/watchlist?limit=100");
          if (!allWatchlistResponse.ok) throw new Error("Request failed");
          allRows = await allWatchlistResponse.json();
        }
        renderSummary(summary);
        renderDashboardRows(rows, allRows);
        firstWatchlistLoad = false;
        lastWatchlistAt = Date.now();
        tickFreshness();
      } catch (error) {
        setFreshness("Update failed", "error");
        rowsEl.innerHTML = `<tr><td class="empty" colspan="6">Dashboard request failed.</td></tr>`;
      } finally {
        watchlistInFlight = false;
        scheduleNextRefresh();
      }
    }

    function renderScanState(state) {
      const status = state.status || "idle";
      const message = state.message || "";
      const stage = state.stage || "idle";
      scanButtonEl.disabled = Boolean(state.running);
      manualAnalyzeButtonEl.disabled = Boolean(state.running);
      scanButtonEl.textContent = state.running ? "Scanning..." : "Run Scan";
      manualAnalyzeButtonEl.textContent = state.running ? "Analyzing..." : "Analyze";
      renderSystemLoad(state);
      scanNoteEl.textContent = `Status: ${status} | Stage: ${stage}${message ? ` | ${message}` : ""}`;
      scanTimeEl.textContent = state.finished_at
        ? `Finished: ${formatDate(state.finished_at)}`
        : state.started_at
          ? `Started: ${formatDate(state.started_at)}`
          : "";

      const steps = state.steps || [];
      scanStepsEl.innerHTML = steps.length
        ? steps.slice(0, 5).map((step) => `
          <div class="scan-step">
            <div class="scan-step-name">${escapeHtml(step.name)} - ${escapeHtml(step.status)}</div>
            <div class="scan-step-detail">${escapeHtml(step.message || "")}</div>
          </div>
        `).join("")
        : `<div class="scan-step"><div class="scan-step-name">Idle</div><div class="scan-step-detail">No scan activity yet.</div></div>`;

      if (state.error) {
        scanErrorEl.style.display = "block";
        scanErrorEl.textContent = state.error;
      } else {
        scanErrorEl.style.display = "none";
        scanErrorEl.textContent = "";
      }

      if (status === "finished") {
        loadDashboard();
      }
    }

    async function loadScanStatus() {
      try {
        const response = await fetch("/api/scan/status");
        if (!response.ok) return;
        renderScanState(await response.json());
      } catch (error) {
        scanNoteEl.textContent = "Scan status unavailable";
      }
    }

    async function startScan() {
      scanButtonEl.disabled = true;
      scanButtonEl.textContent = "Scanning...";
      scanNoteEl.textContent = "Scan status: queued";
      try {
        const response = await fetch("/api/scan", { method: "POST" });
        const state = await response.json();
        renderScanState(state);
      } catch (error) {
        scanButtonEl.disabled = false;
        scanButtonEl.textContent = "Run Scan";
        scanNoteEl.textContent = "Scan failed to start";
      }
    }

    async function startManualAnalyze(event) {
      event.preventDefault();
      const tokenAddress = manualTokenInputEl.value.trim();
      if (!tokenAddress) {
        scanNoteEl.textContent = "Paste a Solana token address first";
        return;
      }
      scanButtonEl.disabled = true;
      manualAnalyzeButtonEl.disabled = true;
      manualAnalyzeButtonEl.textContent = "Analyzing...";
      scanNoteEl.textContent = "Manual token analysis: queued";
      try {
        const response = await fetch("/api/analyze-token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token_address: tokenAddress }),
        });
        const state = await response.json();
        if (!response.ok) {
          throw new Error(state.error || state.message || "Manual analysis failed to start");
        }
        renderScanState(state);
      } catch (error) {
        scanButtonEl.disabled = false;
        manualAnalyzeButtonEl.disabled = false;
        manualAnalyzeButtonEl.textContent = "Analyze";
        scanNoteEl.textContent = error.message || "Manual token analysis failed to start";
      }
    }

    refreshButtonEl.addEventListener("click", loadDashboard);
    scanButtonEl.addEventListener("click", startScan);
    manualAnalyzeFormEl.addEventListener("submit", startManualAnalyze);
    const kbdHelpButtonEl = document.querySelector("#kbdHelpButton");
    if (kbdHelpButtonEl) {
      kbdHelpButtonEl.addEventListener("click", () => toggleCheatsheet());
    }
    const sidebarToggleEl = document.querySelector("#sidebarToggle");
    const appShellEl = document.querySelector(".app-shell");
    if (sidebarToggleEl && appShellEl) {
      sidebarToggleEl.addEventListener("click", () => {
        const collapsed = appShellEl.classList.toggle("sidebar-collapsed");
        sidebarToggleEl.setAttribute("aria-expanded", String(!collapsed));
      });
    }
    document.addEventListener("click", (event) => {
      const button = event.target.closest(".copy-button");
      if (!button) return;
      copyAddress(button.dataset.address || "", button);
    });

    setFreshness("Loading...", "paused");
    loadDashboard();
    loadScanStatus();

    // ---- Real-time event stream (SSE) -----------------------------------
    //
    // Replaces the old setInterval(loadScanStatus, 3000) poll. The
    // browser's EventSource auto-reconnects with exponential back-off if
    // the connection drops; we never need to manage that ourselves.
    // Falls back to polling if the browser somehow lacks EventSource
    // (very rare) or the connection cannot be established.

    let scanEventSource = null;
    let scanFallbackTimer = null;

    function startScanFallbackPoll() {
      if (scanFallbackTimer) return;
      scanFallbackTimer = window.setInterval(loadScanStatus, 3000);
    }

    function stopScanFallbackPoll() {
      if (scanFallbackTimer) {
        clearInterval(scanFallbackTimer);
        scanFallbackTimer = null;
      }
    }

    function connectScanEventStream() {
      if (typeof window.EventSource !== "function") {
        startScanFallbackPoll();
        return;
      }
      try {
        scanEventSource = new EventSource("/api/events");
      } catch (error) {
        startScanFallbackPoll();
        return;
      }
      scanEventSource.addEventListener("scan_state", (event) => {
        try {
          const state = JSON.parse(event.data);
          renderScanState(state);
          stopScanFallbackPoll();
        } catch (error) {
          // Malformed event -- ignore.
        }
      });
      // scan_step events are already covered by scan_state snapshots.
      // Keep the listener registered for future granular UI (e.g. toast
      // when a step fails) so the server-side broadcast isn't wasted.
      scanEventSource.addEventListener("scan_step", () => { /* reserved */ });
      scanEventSource.addEventListener("error", () => {
        // EventSource handles reconnection automatically; we just need
        // to fall back to polling while it figures things out so the
        // user isn't stuck looking at stale data.
        startScanFallbackPoll();
      });
    }

    connectScanEventStream();

    // ---- Whale intercept ticker -----------------------------------------
    //
    // Polls /api/whale-radar every minute and shows the latest 3
    // high-signal alerts as a strip below the brand bar. Strip stays
    // hidden when there's nothing meaningful (no whale signals yet, or
    // empty DB).

    const whaleTickerEl = document.querySelector("#whaleTicker");
    const whaleTickerRailEl = document.querySelector("#whaleTickerRail");
    let whaleTickerSeenIds = new Set();

    function timeAgoShort(value) {
      if (!value) return "—";
      const t = Date.parse(value);
      if (Number.isNaN(t)) return "—";
      const s = Math.max(0, Math.round((Date.now() - t) / 1000));
      if (s < 60)    return `${s}s`;
      if (s < 3600)  return `${Math.floor(s / 60)}m`;
      if (s < 86400) return `${Math.floor(s / 3600)}h`;
      return `${Math.floor(s / 86400)}d`;
    }

    async function loadWhaleTicker() {
      try {
        const r = await fetch("/api/whale-radar?limit=10");
        if (!r.ok) return;
        const data = await r.json();
        const alerts = (data.high_signal_alerts || []).slice(0, 3);
        if (!alerts.length) {
          whaleTickerEl.hidden = true;
          return;
        }
        whaleTickerEl.hidden = false;
        whaleTickerRailEl.innerHTML = alerts.map((a) => {
          const walletAddr = a.wallet_address || "";
          const wallet = walletAddr ? walletAddr.slice(0, 4) + "…" + walletAddr.slice(-4) : "—";
          const token = a.token_symbol || a.token_name || "—";
          const tokenAddr = a.token_address || "";
          const type = String(a.signal_type || "BUY").toUpperCase();
          const amount = a.amount_sol ? `${Number(a.amount_sol).toFixed(2)} SOL` : "";
          const tokenLink = tokenAddr ? `https://solscan.io/token/${encodeURIComponent(tokenAddr)}` : "#";
          return `
            <div class="cb-whale-card" data-id="${a.id}">
              <span class="type">${escapeHtml(type)}</span>
              <strong><a href="${tokenLink}" target="_blank" rel="noopener noreferrer">${escapeHtml(token)}</a></strong>
              <span>by <strong>${escapeHtml(wallet)}</strong></span>
              ${amount ? `<span>· ${escapeHtml(amount)}</span>` : ""}
              <span class="ago">· ${escapeHtml(timeAgoShort(a.signal_at))} ago</span>
            </div>
          `;
        }).join("");
        alerts.forEach((a) => whaleTickerSeenIds.add(a.id));
      } catch (error) {
        /* silent — ticker is non-critical */
      }
    }

    loadWhaleTicker();
    setInterval(loadWhaleTicker, 60_000);

    // 1 Hz tick for the "Updated Xs ago" label so it stays current
    // without re-fetching anything.
    freshnessTimer = window.setInterval(tickFreshness, 1000);
  
