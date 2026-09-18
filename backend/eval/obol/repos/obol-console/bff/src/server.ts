/**
 * BFF entrypoint. Loads config, builds the app, and listens.
 */
import { loadConfig } from './config.js';
import { createApp } from './app.js';
import { createLogger } from './logger.js';

function main(): void {
  const config = loadConfig();
  const logger = createLogger(config.logLevel, { service: 'obol-console-bff' });
  const app = createApp(config);

  const server = app.listen(config.port, () => {
    logger.info('obol-console BFF listening', {
      port: config.port,
      env: config.nodeEnv,
      gateway: config.gateway.baseUrl,
      ledger: config.ledger.baseUrl,
      static: config.staticDir ?? '(none)',
    });
  });

  const shutdown = (signal: string): void => {
    logger.info('shutting down', { signal });
    server.close(() => process.exit(0));
    // Force-exit if connections linger.
    setTimeout(() => process.exit(1), 10_000).unref();
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

main();
