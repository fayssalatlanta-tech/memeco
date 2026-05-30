/**
 * Thin wrappers around the Memeco JSON API. Keeps fetch calls in one
 * place so we can add interceptors, retries, or a request id later.
 */

async function getJson(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`HTTP ${r.status} ${path}`);
  return r.json();
}

export const api = {
  health:        () => getJson("/api/health"),
  summary:       () => getJson("/api/summary"),
  scanStatus:    () => getJson("/api/scan/status"),
  watchlist:     (params = "") => getJson(`/api/watchlist${params ? `?${params}` : ""}`),
  whaleRadar:    (params = "") => getJson(`/api/whale-radar${params ? `?${params}` : ""}`),
  walletDetail:  (wallet) => getJson(`/api/wallet-detail?wallet=${encodeURIComponent(wallet)}`),
  tokenDetail:   (runId, tokenId) =>
    getJson(`/api/token-detail?run_id=${encodeURIComponent(runId)}&token_id=${encodeURIComponent(tokenId)}`),
  system:        () => getJson("/api/system"),
};
