/*
 * Shared front-end utilities for Memeco dashboard pages.
 *
 * All exports live on `window.MemecoUtils`. Page scripts opt in by
 * reading `MemecoUtils.foo`, e.g.:
 *
 *     const { escapeHtml, formatNumber } = window.MemecoUtils;
 *
 * Pages that still define their own `escapeHtml` etc. as inline
 * function declarations will simply shadow these — no behavior change.
 * Migrate page-by-page.
 */
(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // Alias: token_detail uses `attr(value)` as a synonym for escapeHtml.
  function attr(value) {
    return escapeHtml(value);
  }

  function numberOrNull(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function asNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function formatNumber(value, digits = 2) {
    const number = numberOrNull(value);
    if (number === null) return "N/A";
    return number.toLocaleString(undefined, {
      maximumFractionDigits: digits,
      minimumFractionDigits:
        number !== 0 && Math.abs(number) < 10 ? Math.min(digits, 2) : 0,
    });
  }

  function formatPercent(value, digits = 2) {
    const number = numberOrNull(value);
    if (number === null) return "N/A";
    return `${formatNumber(number, digits)}%`;
  }

  function formatMoney(value) {
    const number = numberOrNull(value);
    if (number === null) return "N/A";
    if (Math.abs(number) >= 1_000_000) return `$${formatNumber(number / 1_000_000, 2)}M`;
    if (Math.abs(number) >= 1_000) return `$${formatNumber(number / 1_000, 2)}K`;
    return `$${formatNumber(number, 2)}`;
  }

  function formatPrice(value) {
    const number = numberOrNull(value);
    if (number === null) return "N/A";
    if (number === 0) return "$0";
    if (number < 0.000001) return `$${number.toExponential(2)}`;
    if (number < 0.01) return `$${number.toPrecision(4)}`;
    return `$${number.toLocaleString(undefined, { maximumFractionDigits: 6 })}`;
  }

  function formatDate(value) {
    if (!value) return "N/A";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "N/A";
    return date.toLocaleString();
  }

  function formatAgeMinutes(value) {
    const minutes = numberOrNull(value);
    if (minutes === null) return "N/A";
    if (minutes < 60) return `${Math.max(0, Math.round(minutes))}m`;
    const hours = minutes / 60;
    if (hours < 48) return `${hours.toFixed(1)}h`;
    return `${(hours / 24).toFixed(1)}d`;
  }

  function shortAddress(value, head = 6, tail = 6) {
    const text = String(value || "");
    if (!text) return "N/A";
    if (text.length <= head + tail + 3) return text;
    return `${text.slice(0, head)}...${text.slice(-tail)}`;
  }

  function shortWallet(value) {
    return shortAddress(value, 5, 5);
  }

  function parseDetails(value) {
    if (!value) return {};
    if (typeof value === "object") return value;
    try {
      return JSON.parse(value);
    } catch (error) {
      return {};
    }
  }

  window.MemecoUtils = Object.freeze({
    escapeHtml,
    attr,
    numberOrNull,
    asNumber,
    formatNumber,
    formatPercent,
    formatMoney,
    formatPrice,
    formatDate,
    formatAgeMinutes,
    shortAddress,
    shortWallet,
    parseDetails,
  });
})();
