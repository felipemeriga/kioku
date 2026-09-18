/**
 * BFF configuration, read once from the environment. The BFF is the only tier
 * that holds upstream URLs and API keys — the web SPA never sees them.
 */
export interface UpstreamConfig {
  baseUrl: string;
  apiKey: string;
}

export interface Config {
  port: number;
  nodeEnv: 'development' | 'production' | 'test';
  logLevel: string;
  upstreamTimeoutMs: number;
  platformId: string;
  gateway: UpstreamConfig;
  ledger: UpstreamConfig;
  /** Directory of built SPA assets to serve; empty means "API only". */
  staticDir: string | null;
}

function required(name: string, fallback?: string): string {
  const v = process.env[name] ?? fallback;
  if (v === undefined || v === '') {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return v;
}

function intEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  const n = Number.parseInt(raw, 10);
  if (Number.isNaN(n)) throw new Error(`Env ${name} must be an integer, got "${raw}"`);
  return n;
}

export function loadConfig(env = process.env): Config {
  const nodeEnv = (env.NODE_ENV ?? 'development') as Config['nodeEnv'];
  return {
    port: intEnv('PORT', 8787),
    nodeEnv,
    logLevel: env.LOG_LEVEL ?? 'info',
    upstreamTimeoutMs: intEnv('UPSTREAM_TIMEOUT_MS', 8000),
    platformId: env.CONSOLE_PLATFORM_ID ?? 'plat_marisqueira',
    gateway: {
      baseUrl: required('GATEWAY_BASE_URL', 'http://localhost:8080'),
      apiKey: required('GATEWAY_API_KEY', 'obol_gw_test_key'),
    },
    ledger: {
      baseUrl: required('LEDGER_BASE_URL', 'http://localhost:8000'),
      apiKey: required('LEDGER_API_KEY', 'obol_lg_test_key'),
    },
    staticDir: env.STATIC_DIR && env.STATIC_DIR !== '' ? env.STATIC_DIR : null,
  };
}
