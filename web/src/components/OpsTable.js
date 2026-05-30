/**
 * Cyberpunk table renderer.
 *
 *   OpsTable({ headers: ['A', 'B'], rows: [['…', '…']], emptyMessage: 'No rows' })
 *
 * Cell values can be plain strings (auto-escaped) or pre-rendered
 * objects from `raw(html)` for HTML interpolation.
 */

import { h, raw } from "../lib/dom.js";

export function OpsTable({ headers = [], rows = [], emptyMessage = "No data yet." }) {
  if (!rows.length) {
    return h`<div class="cy-empty">${emptyMessage}</div>`;
  }
  const headerHtml = headers.map((label) => h`<th>${label}</th>`).join("");
  const bodyHtml = rows.map((cells) => {
    const tds = cells.map((cell) => {
      if (cell && typeof cell === "object" && cell.value !== undefined && cell.html === true) {
        return `<td${cell.muted ? ' class="muted"' : ""}>${cell.value}</td>`;
      }
      return h`<td${cell && cell.muted ? raw(' class="muted"') : ""}>${cell == null ? "—" : cell}</td>`;
    }).join("");
    return `<tr>${tds}</tr>`;
  }).join("");
  return raw(`
    <div style="overflow-x:auto;">
      <table class="cy-table">
        <thead><tr>${headerHtml}</tr></thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `).value;
}
