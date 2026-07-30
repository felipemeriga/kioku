/**
 * URL topology mapping between the three kioku services.
 *
 * The CLI knows one of the service URLs (the REST api_base, or the MCP `/sse`
 * URL from a repo's .mcp.json) and frequently needs another. There are TWO
 * deployment topologies and every derivation must handle both:
 *
 *   dev   — one host, distinguished by PORT:
 *             REST http://localhost:8000   MCP http://localhost:8001   web :5174
 *   prod  — distinct SUBDOMAINS on :443:
 *             REST https://<s>.api.<domain> MCP https://<s>.mcp.<domain>
 *             web  https://<s>.<domain>     (frontend has no api/mcp label)
 *
 * Historically these were derived inline with `.replace(/:8001$/, ":8000")`,
 * which is a no-op in prod (different subdomains, no port) and silently sent
 * REST calls to the MCP host. These helpers are the single source of truth.
 */

const DEV_REST_PORT = "8000";
const DEV_MCP_PORT = "8001";
const DEV_WEB_PORT = "5174";

/** MCP url (e.g. .../sse) → REST api base origin (no path). */
export function mcpUrlToRestBase(mcpUrl: string): string {
  const u = new URL(mcpUrl);
  if (u.port === DEV_MCP_PORT) return `${u.protocol}//${u.hostname}:${DEV_REST_PORT}`;
  // prod: swap the `mcp` subdomain label for `api`
  const host = u.hostname.replace(/^mcp\./, "api.").replace(/\.mcp\./, ".api.");
  return `${u.protocol}//${host}`;
}

/** REST api base → MCP base origin (no `/sse`, no path). */
export function restBaseToMcpBase(apiBase: string): string {
  const u = new URL(apiBase);
  if (u.port === DEV_REST_PORT) return `${u.protocol}//${u.hostname}:${DEV_MCP_PORT}`;
  // prod: swap the `api` subdomain label for `mcp`
  const host = u.hostname.replace(/^api\./, "mcp.").replace(/\.api\./, ".mcp.");
  return `${u.protocol}//${host}`;
}

/** REST api base → web UI origin. */
export function restBaseToWebUrl(apiBase: string): string {
  const u = new URL(apiBase);
  if (u.port === DEV_REST_PORT) return `${u.protocol}//${u.hostname}:${DEV_WEB_PORT}`;
  // prod: drop the `api.` label → frontend root (kioku.api.x → kioku.x)
  const host = u.hostname.replace(/^api\./, "").replace(/\.api\./, ".");
  return `${u.protocol}//${host}`;
}
