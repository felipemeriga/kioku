/**
 * Express application factory. Kept separate from server.ts so tests can mount
 * the app in-process (supertest) without binding a port.
 */
import express, { type Express } from 'express';
import path from 'node:path';
import type { Config } from './config.js';
import { buildDeps, type Deps } from './deps.js';
import { requestId } from './middleware/requestId.js';
import { errorHandler, notFoundHandler } from './middleware/errorHandler.js';
import { apiRouter } from './routes/index.js';

export interface AppOptions {
  /** Override the dependency container (tests inject mock clients). */
  deps?: Deps;
}

export function createApp(config: Config, options: AppOptions = {}): Express {
  const deps = options.deps ?? buildDeps(config);
  const app = express();

  app.disable('x-powered-by');
  app.use(express.json({ limit: '256kb' }));
  app.use(requestId(config.logLevel));

  // All console API surface lives under /api. The web SPA talks only here.
  app.use('/api', apiRouter(deps));
  app.use('/api', notFoundHandler);

  // Optionally serve the built SPA (production single-container mode).
  if (config.staticDir) {
    const dir = path.resolve(config.staticDir);
    app.use(express.static(dir));
    // SPA fallback: any non-API GET returns index.html for client routing.
    app.get('*', (_req, res) => {
      res.sendFile(path.join(dir, 'index.html'));
    });
  }

  app.use(errorHandler);
  return app;
}
