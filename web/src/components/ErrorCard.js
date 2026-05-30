/**
 * Red-edge error card used by the system page (and any future page
 * that wants to surface backend failures cleanly).
 */

import { h } from "../lib/dom.js";

export function ErrorCard({ title = "ERROR", subtitle = "", message = "" }) {
  return h`
    <div class="cy-error">
      <div class="meta">${title}${subtitle ? ` · ${subtitle}` : ""}</div>
      <div class="msg">${(message || "(no message)").slice(0, 800)}</div>
    </div>
  `;
}
