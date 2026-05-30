/**
 * Sticky cyberpunk brand bar shared across every Memeco page.
 *
 *   BrandBar({ name, tag, active, right })
 *     name   — uppercase brand line, e.g. "OPS DECK"
 *     tag    — small uppercase secondary line
 *     active — id of the currently active nav link
 *               ("dashboard" | "whale" | "wallet" | "token" | "system")
 *     right  — optional safe-HTML to inject in the right slot
 */

import { h, raw } from "../lib/dom.js";

const NAV = [
  { id: "dashboard", label: "DASHBOARD",   href: "/" },
  { id: "whale",     label: "WHALE RADAR", href: "/whale-radar" },
  { id: "system",    label: "SYSTEM",      href: "/system" },
  // wallet / token are deep-link pages and don't appear in the
  // central brand-bar nav; their own pages render their nav locally.
];

export function BrandBar({ name = "MEMECO", tag = "QUANT INTELLIGENCE", active, right = "" }) {
  const navHtml = NAV.map((item) => {
    const cls = active === item.id ? "cy-nav-link is-active" : "cy-nav-link";
    return `<a class="${cls}" href="${item.href}">${item.label}</a>`;
  }).join("");

  return h`
    <header class="cy-brand-bar">
      <div class="cy-brand">
        <span class="cy-brand-mark">▲</span>
        <div>
          <div class="cy-brand-name">${name}</div>
          <div class="cy-brand-tag">${tag}</div>
        </div>
      </div>
      <nav class="cy-nav" aria-label="Workspace">${raw(navHtml)}</nav>
      <div class="cy-brand-right">${raw(right)}</div>
    </header>
  `;
}
