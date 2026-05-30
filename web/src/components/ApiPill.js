/**
 * Pulsing status pill shown in brand-bar right slot.
 *
 *   ApiPill({ id?, text })
 */

import { h } from "../lib/dom.js";

export function ApiPill({ id = "", text = "Loading…" }) {
  const idAttr = id ? ` id="${id}"` : "";
  return h`<span class="cy-pill"${id ? ` id=${id}` : ""}><span class="dot"></span><span>${text}</span></span>`;
}
