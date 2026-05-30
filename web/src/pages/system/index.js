/**
 * Memeco — Ops Deck (Vite-built version).
 *
 * Same data and visual identity as app/static/system.html, but built
 * from shared components in ../../components and shared styles in
 * ../../styles. This is the reference for migrating the other pages.
 */

import "../../styles/tokens.css";
import "../../styles/cyberpunk.css";

import { api } from "../../lib/api.js";
import { timeAgo } from "../../lib/time.js";
import { h, raw, mount } from "../../lib/dom.js";

import { BrandBar } from "../../components/BrandBar.js";
import { OpsHud } from "../../components/OpsHud.js";
import { OpsTable } from "../../components/OpsTable.js";
import { ApiPill } from "../../components/ApiPill.js";
import { ErrorCard } from "../../components/ErrorCard.js";

const appEl = document.querySelector("#app");

function shell(content) {
  const right = ApiPill({ id: "lastUpdated", text: "Loading…" });
  return BrandBar({
    name: "OPS DECK",
    tag: "SYSTEM · TELEMETRY · HEALTH",
    active: "system",
    right,
  }) + content;
}

function configCard(cfg = {}) {
  const status = (configured) => configured
    ? raw(`<span class="val good">CONFIGURED</span>`)
    : raw(`<span class="val bad">MISSING</span>`);
  const tile = (label, configured, sub) => h`
    <div class="cy-stat">
      <div class="lbl">${label}</div>
      ${status(configured)}
      <div class="sub">${sub}</div>
    </div>
  `;
  return raw(`
    <article class="cy-panel">
      <header class="cy-section-head">
        <h2>EXTERNAL APIS</h2>
        <div class="cy-section-note">Configuration status from .env</div>
      </header>
      <div class="cy-stat-grid">
        ${tile("HELIUS",        cfg.helius_configured,           "HELIUS_API_KEY")}
        ${tile("RUGCHECK",      cfg.rugcheck_configured,         "RUGCHECK_API_KEY")}
        ${tile("WEBHOOK URL",   cfg.whale_webhook_url_configured,"WHALE_WEBHOOK_URL")}
        ${tile("WEBHOOK AUTH",  cfg.whale_webhook_auth_configured,"WHALE_WEBHOOK_AUTH_HEADER")}
      </div>
    </article>
  `).value;
}

function webhookCard(wh) {
  if (!wh) {
    return h`
      <article class="cy-panel">
        <header class="cy-section-head">
          <h2>WHALE WEBHOOK</h2>
          <div class="cy-section-note">Helius watcher serving /api/whale-signal</div>
        </header>
        <div class="cy-empty">No webhook configured. Run "Sync Webhook" on Whale Radar.</div>
      </article>
    `;
  }
  const tone = wh.active ? "good" : "warn";
  return h`
    <article class="cy-panel">
      <header class="cy-section-head">
        <h2>WHALE WEBHOOK</h2>
        <div class="cy-section-note">Helius watcher serving /api/whale-signal</div>
      </header>
      <div class="cy-stat-grid">
        <div class="cy-stat">
          <div class="lbl">STATUS</div>
          <div class="val ${tone}">${wh.status || "—"}</div>
        </div>
        <div class="cy-stat"><div class="lbl">WATCHED</div><div class="val">${wh.watched ?? "—"}</div></div>
        <div class="cy-stat"><div class="lbl">UPDATED</div><div class="val muted">${timeAgo(wh.updated_at)}</div></div>
        <div class="cy-stat"><div class="lbl">LAST ERROR</div><div class="val muted">${wh.last_error ?? "—"}</div></div>
      </div>
    </article>
  `;
}

function decisionsHud(dec = {}) {
  return OpsHud([
    { label: "TOTAL DECISIONS", value: dec.total_decisions ?? 0 },
    { label: "PASS",            value: dec.pass ?? 0 },
    { label: "PASS · HIGH RISK", value: dec.pass_high_risk ?? 0 },
    { label: "LATEST DECISION", value: timeAgo(dec.latest_at) },
  ]);
}

function activityPanel(rows = []) {
  const tableHtml = OpsTable({
    headers: ["Source", "1h", "24h", "Last seen"],
    rows: rows.map((r) => [
      r.source || "—",
      String(r.req_1h ?? 0),
      { value: String(r.req_24h ?? 0), html: true, muted: true },
      { value: timeAgo(r.last_seen),   html: true, muted: true },
    ]),
    emptyMessage: "No raw_api_snapshots yet. Run a scan.",
  });
  return raw(`
    <article class="cy-panel">
      <header class="cy-section-head">
        <h2>API ACTIVITY (last 1h / 24h)</h2>
        <div class="cy-section-note">Counts of raw_api_snapshots rows by source — proxy for Helius / DexScreener / RugCheck request volume</div>
      </header>
      ${tableHtml}
    </article>
  `).value;
}

function storagePanel(data) {
  const size = data.db_size || {};
  const hyper = data.hypertables || [];
  const retention = data.retention_policies || [];
  const retMap = new Map(retention.map((r) => [r.table_name, r.drop_after]));
  const tableHtml = OpsTable({
    headers: ["Hypertable", "Chunks", "Retention"],
    rows: hyper.map((t) => [
      t.table_name,
      { value: String(t.chunk_count ?? 0), html: true, muted: true },
      { value: String(retMap.get(t.table_name) || "—"), html: true, muted: true },
    ]),
    emptyMessage: "TimescaleDB not detected.",
  });
  return raw(`
    <article class="cy-panel">
      <header class="cy-section-head">
        <h2>STORAGE & RETENTION</h2>
        <div class="cy-section-note">TimescaleDB hypertables and retention policies</div>
      </header>
      <div class="cy-stat-grid">
        <div class="cy-stat"><div class="lbl">DB SIZE</div><div class="val">${size.db_size_pretty ?? "—"}</div></div>
        <div class="cy-stat"><div class="lbl">HYPERTABLES</div><div class="val">${hyper.length}</div></div>
      </div>
      <div style="margin-top: 12px;">${tableHtml}</div>
    </article>
  `).value;
}

function failuresPanel(errors = []) {
  const body = errors.length
    ? errors.map((e) => ErrorCard({
        title: `RUN #${e.id}`,
        subtitle: `${e.source || ""} · ${timeAgo(e.finished_at || e.started_at)}`,
        message: e.error_message || "(no message)",
      })).join("")
    : `<div class="cy-empty">No failed runs in recent history. ☕</div>`;
  return raw(`
    <article class="cy-panel">
      <header class="cy-section-head">
        <h2>RECENT FAILURES</h2>
        <div class="cy-section-note">Last 5 failed or errored ingestion runs</div>
      </header>
      ${body}
    </article>
  `).value;
}

function pageBody(data) {
  return [
    decisionsHud(data.decisions),
    raw(`<section style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">
          ${configCard(data.config)}${webhookCard(data.whale_webhook)}
        </section>`).value,
    activityPanel(data.activity),
    raw(`<section style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">
          ${storagePanel(data)}${failuresPanel(data.failed_runs)}
        </section>`).value,
  ].join("");
}

async function load() {
  try {
    const data = await api.system();
    mount(appEl, shell(pageBody(data)));
    // Update the pulsing pill text after render.
    const pill = document.querySelector("#lastUpdated span:last-child");
    if (pill) pill.textContent = `Updated ${timeAgo(new Date().toISOString())}`;
  } catch (error) {
    mount(appEl, shell(ErrorCard({
      title: "FETCH",
      message: error.message,
    })));
  }
}

load();
setInterval(load, 30_000);
