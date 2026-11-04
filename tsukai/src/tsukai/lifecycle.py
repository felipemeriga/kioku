"""Private artifact cleanup after execution ownership has been reaped/fenced."""

import asyncio
import os
import shutil
from pathlib import Path


def remove_artifacts(record, workspace_root, native_root):
    root = Path(workspace_root).resolve()
    native = Path(native_root).resolve()
    for artifact in record["artifacts"]:
        workspace = Path(artifact["workspace"])
        resolved = workspace.resolve()
        if resolved == root or root not in resolved.parents:
            raise ValueError("workspace cleanup path outside configured root")
        if workspace.exists() or workspace.is_symlink():
            if workspace.is_symlink():
                workspace.unlink(missing_ok=True)
            elif workspace.exists():
                shutil.rmtree(workspace)
        session = artifact["native_session_id"]
        # Native credential/config files are never read or removed. Only session-named
        # artifacts in documented transcript/task/history trees are eligible.
        for name in ("projects", "file-history", "tasks", "todos"):
            subtree = native / name
            if not subtree.exists():
                continue
            if native not in subtree.resolve().parents:
                raise ValueError("native artifact tree outside configured root")
            for path in list(subtree.rglob("*")):
                if path.name not in {session, session + ".jsonl", session + ".json"}:
                    continue
                if path.is_symlink():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
                # Dedicated per-session cwd produces a dedicated native project directory.
                # Remove its session index too, without touching another cwd's transcripts.
                if (
                    name == "projects"
                    and path.parent.name.endswith(session)
                    and path.parent.exists()
                ):
                    shutil.rmtree(path.parent)


async def cleanup_deletions(store, scheduler):
    for record in await store.pending_deletions():
        for job_id in record["job_ids"]:
            await scheduler.cancel(job_id)
        if not await store.deletion_reap_ready(record, scheduler.settings.kill_grace_seconds):
            continue
        native_root = os.getenv("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
        await asyncio.to_thread(
            remove_artifacts, record, scheduler.settings.workspace_dir, native_root
        )
        await store.complete_deletion(record)
