"""Bounded cleanup that repeated cancellation signals cannot interrupt."""

import asyncio
import contextlib


async def complete_cleanup(operation, timeout):
    task = asyncio.create_task(operation)
    deadline = asyncio.get_running_loop().time() + timeout
    while not task.done():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(asyncio.shield(task), remaining)
        except asyncio.CancelledError:
            # The caller may receive API, heartbeat and shutdown cancellation together.
            # Cleanup owns no new inference; keep its original bounded deadline.
            continue
        except TimeoutError:
            if task.done():
                return task.result()
            break
    if task.done():
        return task.result()
    task.cancel()
    _, pending = await asyncio.wait({task}, timeout=1)
    if pending:

        def consume(done):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                done.result()

        task.add_done_callback(consume)
    else:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.result()
    raise TimeoutError("bounded execution cleanup exceeded its deadline")
