/**
 * Edge-stripe HUD strip used on every dashboard. Takes an array of
 * tiles: [{ label, value, hint? }].
 */

import { h, raw } from "../lib/dom.js";

export function OpsHud(tiles = []) {
  if (!tiles.length) return "";
  const cells = tiles.map((t) => h`
    <div>
      <div class="lbl">${t.label}</div>
      <div class="val">${t.value ?? "—"}</div>
      ${t.hint ? raw(`<div class="sub">${t.hint}</div>`) : ""}
    </div>
  `).join("");
  return raw(`<section class="cy-hud">${cells}</section>`).value;
}
