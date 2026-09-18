/**
 * Tiny structured logger. Emits one JSON line per event so the BFF's logs are
 * grep-able and ship cleanly to a log aggregator.
 */
type Level = 'debug' | 'info' | 'warn' | 'error';

const ORDER: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };

export interface Logger {
  debug(msg: string, fields?: Record<string, unknown>): void;
  info(msg: string, fields?: Record<string, unknown>): void;
  warn(msg: string, fields?: Record<string, unknown>): void;
  error(msg: string, fields?: Record<string, unknown>): void;
  child(bindings: Record<string, unknown>): Logger;
}

export function createLogger(level: string, base: Record<string, unknown> = {}): Logger {
  const threshold = ORDER[(level as Level) in ORDER ? (level as Level) : 'info'];

  function emit(lvl: Level, msg: string, fields?: Record<string, unknown>): void {
    if (ORDER[lvl] < threshold) return;
    const line = { ts: new Date().toISOString(), level: lvl, msg, ...base, ...fields };
    const out = lvl === 'error' || lvl === 'warn' ? process.stderr : process.stdout;
    out.write(`${JSON.stringify(line)}\n`);
  }

  return {
    debug: (m, f) => emit('debug', m, f),
    info: (m, f) => emit('info', m, f),
    warn: (m, f) => emit('warn', m, f),
    error: (m, f) => emit('error', m, f),
    child: (bindings) => createLogger(level, { ...base, ...bindings }),
  };
}
