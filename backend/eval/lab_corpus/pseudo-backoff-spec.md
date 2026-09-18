# Spec: computeRetryBackoff (proposed, not yet implemented)

This document specifies a retry helper that does NOT exist in any repository
yet. It is a design artifact only.

## Proposed behavior

`computeRetryBackoff(attempt, baseMs, capMs)` returns the delay before the
next retry:

```
function computeRetryBackoff(attempt, baseMs = 200, capMs = 30000):
    jitter = random(0, baseMs)
    delay = min(capMs, baseMs * 2 ** attempt) + jitter
    return delay
```

- Exponential growth doubles the delay per attempt.
- Full jitter avoids thundering herds after an outage.
- The cap keeps worst-case waits under 30 seconds.

## Open questions

Should the cap be configurable per call site, or global? The spec leans
global until a concrete consumer needs otherwise.
