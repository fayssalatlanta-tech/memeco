/**
 * Tiny DOM helpers. We don't bring in a framework — the pages are
 * small enough that vanilla template strings + `mount()` is the right
 * level of abstraction.
 */

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/**
 * Tagged-template helper. Works just like a normal string template,
 * but explicitly auto-escapes interpolated values unless they are
 * marked as safe via `raw(html)`.
 *
 * Example:
 *   const html = h`<div title=${title}>${raw(innerHtml)}</div>`;
 */
const RAW_MARKER = Symbol("raw");
export function raw(html) {
  return { [RAW_MARKER]: true, value: String(html ?? "") };
}
export function h(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (v && typeof v === "object" && v[RAW_MARKER]) {
      out += v.value;
    } else if (Array.isArray(v)) {
      out += v.map((x) => (x && x[RAW_MARKER] ? x.value : escapeHtml(x))).join("");
    } else {
      out += escapeHtml(v);
    }
    out += strings[i + 1];
  }
  return out;
}

/** Mount a string of HTML into a node. */
export function mount(node, html) {
  if (!node) return;
  node.innerHTML = html;
}
