/**
 * Dependency container. Builds the upstream clients from config and exposes them
 * to the routes. Detecting "mock mode": if a base URL contains "mock" or is
 * empty we serve SPEC fixtures instead of hitting a live service, which lets the
 * console run stand-alone in the eval/demo environment.
 */
import type { Config } from './config.js';
import { HttpClient } from './clients/httpClient.js';
import { GatewayClient } from './clients/gatewayClient.js';
import { LedgerClient } from './clients/ledgerClient.js';

export interface Deps {
  config: Config;
  gateway: GatewayClient;
  ledger: LedgerClient;
}

function isMock(baseUrl: string): boolean {
  return baseUrl.trim() === '' || /mock/i.test(baseUrl);
}

export function buildDeps(config: Config): Deps {
  const gatewayHttp = new HttpClient('gateway', config.gateway, config.upstreamTimeoutMs);
  const ledgerHttp = new HttpClient('ledger', config.ledger, config.upstreamTimeoutMs);
  return {
    config,
    gateway: new GatewayClient(gatewayHttp, isMock(config.gateway.baseUrl)),
    ledger: new LedgerClient(ledgerHttp, isMock(config.ledger.baseUrl)),
  };
}

/** Build a container that forces mock mode — used by tests. */
export function buildMockDeps(config: Config): Deps {
  const gatewayHttp = new HttpClient('gateway', config.gateway, config.upstreamTimeoutMs);
  const ledgerHttp = new HttpClient('ledger', config.ledger, config.upstreamTimeoutMs);
  return {
    config,
    gateway: new GatewayClient(gatewayHttp, true),
    ledger: new LedgerClient(ledgerHttp, true),
  };
}
