import { parseTurn } from "./agent-journal.js";
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
  appendFileSync,
  renameSync,
  symlinkSync,
  utimesSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { fileURLToPath } from "node:url";
import {
  captureSource,
  eventId,
  hash,
  readManifest,
  readJson,
  sessionDir,
  sourceFromHook,
  writeJson,
  type Source,
  type EvidenceManifest,
} from "./agent-evidence.js";
import {
  evidenceApiBase,
  evidenceRequestTimeout,
  syncEvidence,
} from "./agent-evidence-sync.js";
import {
  dispatchEvidence,
  evidenceWorker,
  evidenceStatus,
} from "../commands/evidence.js";
import {
  installClaudeEvidenceHooks,
  installClaudeMemoryCaptureHook,
  removeLegacyCaptureHooks,
} from "./claude.js";
import {
  installCodexEvidenceHooks,
  installCodexMemoryCaptureHook,
  removeCodexCaptureHooks,
} from "./codex.js";
import { parse as parseToml } from "smol-toml";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "kioku-evidence-"));
  const source: Source = {
    path: join(root, "native.jsonl"),
    agent: "claude_code",
    session: "parent",
    root: "parent",
  };
  return {
    root,
    source,
    cleanup: () => rmSync(root, { recursive: true, force: true }),
  };
}
const line = (id: string, text = "余白 café 🦦") =>
  Buffer.from(
    JSON.stringify({
      type: "user",
      uuid: id,
      message: { role: "user", content: text },
    }) + "\r\n",
  );
function reconstruct(
  root: string,
  source: Source,
  m: EvidenceManifest,
  generation?: number,
): Buffer {
  return Buffer.concat(
    m.objects
      .filter(
        (o) =>
          o.kind === "segment" && (!generation || o.generation === generation),
      )
      .map((o) => {
        const data = readFileSync(join(sessionDir(root, source), o.path));
        assert.equal(hash(data), o.sha256);
        return data;
      }),
  );
}
test("native bytes, CRLF and Unicode survive segmentation and duplicate capture", async () => {
  const f = fixture();
  try {
    const bytes = Buffer.concat([line("a"), line("b"), line("c")]);
    writeFileSync(f.source.path, bytes);
    const m = await captureSource(f.root, "folder", f.source, {
      producer: "test",
      target: 120,
    });
    assert.equal(m.objects.length, 3);
    assert.deepEqual(reconstruct(f.root, f.source, m), bytes);
    assert.deepEqual(
      await captureSource(f.root, "folder", f.source, {
        producer: "test",
        target: 120,
      }),
      m,
    );
    assert.equal(
      eventId("folder", f.source, "stream", 1, 1),
      hash('["folder","claude_code","parent","stream",1,1]'),
    );
  } finally {
    f.cleanup();
  }
});
test("partial UTF8 and final lines wait; malformed complete bytes are retained opaque", async () => {
  const f = fixture();
  try {
    const valid = line("a"),
      split = valid.indexOf(Buffer.from("余")) + 1;
    writeFileSync(f.source.path, valid.subarray(0, split));
    const partial = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    assert.equal(partial.objects.length, 0);
    appendFileSync(f.source.path, valid.subarray(split));
    appendFileSync(f.source.path, Buffer.from("not-json\n"));
    const done = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    assert.deepEqual(
      reconstruct(f.root, f.source, done),
      Buffer.concat([valid, Buffer.from("not-json\n")]),
    );
    assert.ok(done.gaps.some((g) => g.code === "parse_error"));
    assert.equal(done.objects[0].generation, 1);
  } finally {
    f.cleanup();
  }
});
test("source rotation and same-size middle rewrite start preserved generations", async () => {
  const f = fixture();
  try {
    const original = Buffer.concat([
      line("a", "x".repeat(10000)),
      line("b", "end"),
    ]);
    writeFileSync(f.source.path, original);
    await captureSource(f.root, "folder", f.source, { producer: "test" });
    const modified = Buffer.from(original);
    modified[6000] = 89;
    writeFileSync(f.source.path, modified);
    utimesSync(f.source.path, new Date(), new Date(Date.now() + 1000));
    const m = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    assert.deepEqual(reconstruct(f.root, f.source, m, 1), original);
    assert.deepEqual(reconstruct(f.root, f.source, m, 2), modified);
    renameSync(f.source.path, f.source.path + ".old");
    writeFileSync(f.source.path, line("c"));
    assert.equal(
      (
        await captureSource(f.root, "folder", f.source, { producer: "test" })
      ).objects.at(-1)!.generation,
      3,
    );
  } finally {
    f.cleanup();
  }
});
test("bounded checkpoints retain pending bytes until the entire source is captured", async () => {
  const f = fixture();
  try {
    const bytes = Buffer.concat(
      Array.from({ length: 20 }, (_, i) => line(String(i))),
    );
    writeFileSync(f.source.path, bytes);
    let m = await captureSource(f.root, "folder", f.source, {
      producer: "test",
      maxBytes: 320,
    });
    assert.ok(m.coverage!.pending_bytes > 0);
    while (m.coverage!.pending_bytes)
      m = await captureSource(f.root, "folder", f.source, {
        producer: "test",
        maxBytes: 320,
      });
    assert.deepEqual(reconstruct(f.root, f.source, m), bytes);
  } finally {
    f.cleanup();
  }
});
test("Stop finalizes a journal alias after progress already consumed every byte", async () => {
  const f = fixture();
  try {
    writeFileSync(f.source.path, line("user-id"));
    const progress = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    assert.equal(progress.journal_links.length, 0);
    const stop = await captureSource(f.root, "folder", f.source, {
      producer: "test",
      finalizeJournal: true,
    });
    assert.equal(
      stop.journal_links[0].journal_entry_id,
      "claude_code:parent:user-id",
    );
    assert.equal(stop.objects.length, progress.objects.length);
    assert.ok(stop.revision > progress.revision);
  } finally {
    f.cleanup();
  }
});
test("attachments are private-root bounded, missing files retry without new lines", async () => {
  const f = fixture();
  try {
    const attachment = join(f.root, "parent", "tool-results", "output.txt");
    mkdirSync(join(f.root, "parent", "tool-results"), { recursive: true });
    writeFileSync(
      f.source.path,
      line("a", `Full output saved to: ${attachment}\n`),
    );
    const m = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    assert.ok(m.gaps.some((g) => g.code === "attachment_missing"));
    writeFileSync(attachment, "full original output");
    const repaired = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    assert.equal(
      repaired.objects.filter((o) => o.kind === "attachment").length,
      1,
    );
    assert.ok(!repaired.gaps.some((g) => g.code === "attachment_missing"));
    const outside = join(f.root, "secret.txt");
    writeFileSync(outside, "not authorized");
    symlinkSync(outside, join(f.root, "parent", "tool-results", "escape"));
    appendFileSync(
      f.source.path,
      line(
        "b",
        `Full output saved to: ${join(f.root, "parent", "tool-results", "escape")}\n`,
      ),
    );
    const escaped = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    assert.ok(escaped.gaps.some((g) => g.code === "attachment_outside_source"));
  } finally {
    f.cleanup();
  }
});
test("Codex child start uses thread ID, and grandchildren nest under parent", () => {
  const f = fixture();
  try {
    const src = sourceFromHook("codex", {
      session_id: "parent",
      agent_id: "child",
      transcript_path: f.source.path,
      hook_event_name: "SubagentStart",
    });
    assert.equal(src!.session, "child");
    assert.equal(src!.parent, "parent");
    assert.equal(
      sessionDir(f.root, {
        ...f.source,
        session: "grandchild",
        root: "parent",
        parent: "child",
        ancestors: ["parent", "child"],
      }),
      join(
        f.root,
        ".kioku/memory/originals/claude_code/parent/subagents/child/subagents/grandchild",
      ),
    );
  } finally {
    f.cleanup();
  }
});
test("live locks serialize and two processes recover one dead owner safely", async () => {
  const f = fixture();
  try {
    const lock = join(f.root, "lock");
    mkdirSync(lock);
    writeFileSync(join(lock, "owner"), "99999999:dead");
    const module = fileURLToPath(
        new URL("./agent-evidence.js", import.meta.url),
      ),
      log = join(f.root, "order");
    const code = `import {withEvidenceLock} from ${JSON.stringify(new URL("file://" + module).href)};import {appendFileSync} from 'node:fs';await withEvidenceLock(${JSON.stringify(lock)},async()=>{appendFileSync(${JSON.stringify(log)},'start\\n');await new Promise(r=>setTimeout(r,60));appendFileSync(${JSON.stringify(log)},'end\\n');});`;
    await Promise.all(
      Array.from(
        { length: 2 },
        () =>
          new Promise<void>((done, reject) => {
            const child = spawn(
              process.execPath,
              ["--input-type=module", "-e", code],
              { stdio: "pipe" },
            );
            let error = "";
            child.stderr.on("data", (d) => (error += String(d)));
            child.on("exit", (c) =>
              c === 0 ? done() : reject(new Error(error)),
            );
          }),
      ),
    );
    assert.equal(readFileSync(log, "utf8"), "start\nend\nstart\nend\n");
  } finally {
    f.cleanup();
  }
});
test("new hook installation preserves journal and unrelated handlers across re-init", () => {
  const f = fixture(),
    previous = process.env.CODEX_HOME;
  process.env.CODEX_HOME = join(f.root, "codex");
  try {
    installClaudeMemoryCaptureHook(f.root);
    installCodexMemoryCaptureHook();
    installClaudeEvidenceHooks(f.root);
    installCodexEvidenceHooks();
    assert.equal(installClaudeEvidenceHooks(f.root).addedHook, false);
    assert.equal(installCodexEvidenceHooks().addedHook, false);
    removeLegacyCaptureHooks(f.root);
    removeCodexCaptureHooks();
    const claude = JSON.parse(
      readFileSync(join(f.root, ".claude/settings.local.json"), "utf8"),
    );
    assert.equal(
      claude.hooks.Stop[0].hooks.length + claude.hooks.Stop[1].hooks.length,
      2,
    );
    const codex = parseToml(
      readFileSync(join(process.env.CODEX_HOME, "config.toml"), "utf8"),
    ) as unknown as {
      hooks: { Stop: Array<{ hooks: Array<{ command: string }> }> };
    };
    assert.equal(codex.hooks.Stop.flatMap((g) => g.hooks).length, 2);
  } finally {
    if (previous === undefined) delete process.env.CODEX_HOME;
    else process.env.CODEX_HOME = previous;
    f.cleanup();
  }
});
test("URL topology preserves custom ports and explicit override", () => {
  const old = process.env.KIOKU_API_BASE;
  delete process.env.KIOKU_API_BASE;
  try {
    assert.equal(
      evidenceApiBase("http://localhost:8001/sse"),
      "http://localhost:8000",
    );
    assert.equal(
      evidenceApiBase("https://kioku.mcp.example.com/sse"),
      "https://kioku.api.example.com",
    );
    assert.equal(
      evidenceApiBase("http://127.0.0.1:43210/mcp"),
      "http://127.0.0.1:43210",
    );
    process.env.KIOKU_API_BASE = "http://localhost:1234/";
    assert.equal(evidenceApiBase("https://other/mcp"), "http://localhost:1234");
  } finally {
    if (old === undefined) delete process.env.KIOKU_API_BASE;
    else process.env.KIOKU_API_BASE = old;
  }
});

async function server(
  handler: (
    request: IncomingMessage,
    response: ServerResponse,
    bytes: Buffer,
  ) => void,
) {
  const http = createServer(async (req, res) => {
    const chunks: Buffer[] = [];
    for await (const part of req) chunks.push(Buffer.from(part));
    handler(req, res, Buffer.concat(chunks));
  });
  await new Promise<void>((done) => http.listen(0, "127.0.0.1", done));
  const address = http.address() as { port: number };
  return {
    url: `http://127.0.0.1:${address.port}`,
    close: () =>
      new Promise<void>((done, reject) =>
        http.close((e) => (e ? reject(e) : done())),
      ),
  };
}
function config(root: string, url: string) {
  mkdirSync(join(root, ".claude"), { recursive: true });
  writeJson(join(root, ".claude/kioku-state.json"), { folder_id: "folder" });
  writeJson(join(root, ".mcp.json"), {
    mcpServers: {
      kioku: {
        url: url + "/mcp",
        headers: { Authorization: "Bearer scoped-test-key" },
      },
    },
  });
}
test("scoped prepare/upload/commit is hash-checked, idempotent and reconciles CAS", async () => {
  const f = fixture();
  let revision = 7,
    conflict = true,
    uploads = 0;
  const ids = new Set<string>();
  const remote = await server((req, res, bytes) => {
    res.setHeader("Content-Type", "application/json");
    assert.equal(req.headers.authorization, "Bearer scoped-test-key");
    const path = req.url!;
    if (path.endsWith("/capabilities")) {
      res.end(
        JSON.stringify({
          enabled: true,
          schema: 1,
          max_object_bytes: 67108864,
          max_batch_objects: 256,
        }),
      );
      return;
    }
    if (req.method === "PUT") {
      uploads++;
      ids.add(path.split("/").at(-1)!);
      res.end("{}");
      return;
    }
    if (path.endsWith("/batches")) {
      const b = JSON.parse(bytes.toString());
      assert.ok(!JSON.stringify(b).includes("native.jsonl"));
      res.end(
        JSON.stringify({
          session_id: "server-id",
          revision,
          missing_objects: b.objects
            .filter((o: { id: string }) => !ids.has(o.id))
            .map((o: { id: string }) => o.id),
        }),
      );
      return;
    }
    if (path.endsWith("/commit") && conflict) {
      conflict = false;
      res.statusCode = 409;
      res.end(JSON.stringify({ detail: { current_revision: revision } }));
      return;
    }
    revision++;
    res.end(
      JSON.stringify({
        status: "accepted",
        session_id: "server-id",
        revision,
        index_status: "pending",
      }),
    );
  });
  try {
    config(f.root, remote.url);
    writeFileSync(f.source.path, line("a"));
    const m = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    await syncEvidence(f.root, "folder", f.source, m, true);
    await syncEvidence(f.root, "folder", f.source, m, true);
    assert.equal(uploads, 1);
    assert.equal(revision, 8);
  } finally {
    await remote.close();
    f.cleanup();
  }
});
test("failed and unsupported backends retain originals; dispatch rejects symlink escape", async () => {
  const f = fixture();
  const old = process.env.CLAUDE_CONFIG_DIR;
  const home = join(f.root, "claude-home");
  process.env.CLAUDE_CONFIG_DIR = home;
  const remote = await server((_req, res) => {
    res.statusCode = 503;
    res.end("{}");
  });
  try {
    config(f.root, remote.url);
    mkdirSync(join(home, "projects"), { recursive: true });
    const outside = join(f.root, "outside.jsonl");
    writeFileSync(outside, line("a"));
    const link = join(home, "projects", "escape.jsonl");
    symlinkSync(outside, link);
    assert.equal(
      await dispatchEvidence(f.root, "claude_code", {
        session_id: "parent",
        transcript_path: link,
      }),
      null,
    );
    const wrong = join(home, "projects", "wrong.jsonl");
    writeFileSync(
      wrong,
      JSON.stringify({
        type: "user",
        cwd: "/tmp",
        message: { content: "wrong" },
      }) + "\n",
    );
    assert.equal(
      await dispatchEvidence(f.root, "claude_code", {
        session_id: "wrong",
        transcript_path: wrong,
      }),
      null,
    );
    writeFileSync(f.source.path, line("a"));
    const m = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    await assert.rejects(syncEvidence(f.root, "folder", f.source, m, true));
    assert.deepEqual(
      reconstruct(f.root, f.source, readManifest(f.root, f.source)!),
      line("a"),
    );
    writeJson(join(f.root, ".kioku/memory/.evidence-state/settings.json"), {
      original_evidence_enabled: false,
    });
    assert.equal(evidenceStatus(f.root).enabled, false);
  } finally {
    if (old === undefined) delete process.env.CLAUDE_CONFIG_DIR;
    else process.env.CLAUDE_CONFIG_DIR = old;
    await remote.close();
    f.cleanup();
  }
});
test("worker drains a 130 MiB session across bounded checkpoints before acknowledging its job", async () => {
  const f = fixture(),
    oldClaude = process.env.CLAUDE_CONFIG_DIR,
    oldXdg = process.env.XDG_CONFIG_HOME;
  const home = join(f.root, "claude-home"),
    project = join(home, "projects", "poc");
  process.env.CLAUDE_CONFIG_DIR = home;
  process.env.XDG_CONFIG_HOME = join(f.root, "config");
  mkdirSync(project, { recursive: true });
  let uploadedBytes = 0,
    revision = 0,
    offline = true;
  const remote = await server((req, res, bytes) => {
    res.setHeader("Content-Type", "application/json");
    if (offline) {
      res.statusCode = 503;
      res.end("{}");
      return;
    }
    if (req.url!.endsWith("/capabilities")) {
      res.end(
        JSON.stringify({
          enabled: true,
          schema: 1,
          max_object_bytes: 67108864,
          max_batch_objects: 256,
        }),
      );
      return;
    }
    if (req.method === "PUT") {
      uploadedBytes += bytes.length;
      res.end("{}");
      return;
    }
    if (req.url!.endsWith("/batches")) {
      const b = JSON.parse(bytes.toString());
      res.end(
        JSON.stringify({
          session_id: "large-id",
          revision,
          missing_objects: b.objects.map((o: { id: string }) => o.id),
        }),
      );
      return;
    }
    revision++;
    res.end(
      JSON.stringify({
        status: "accepted",
        session_id: "large-id",
        revision,
        index_status: "pending",
      }),
    );
  });
  try {
    config(f.root, remote.url);
    const source = { ...f.source, path: join(project, "parent.jsonl") };
    writeFileSync(source.path, line("user"));
    const record = Buffer.from(
      JSON.stringify({ type: "future", content: "X".repeat(128 * 1024) }) +
        "\n",
    );
    for (let n = 0; n < 1040; n++) appendFileSync(source.path, record);
    await dispatchEvidence(f.root, "claude_code", {
      session_id: "parent",
      transcript_path: source.path,
      hook_event_name: "Stop",
    });
    await evidenceWorker(f.root, true, { scheduleRetry: () => {} });
    assert.equal(readManifest(f.root, source)!.coverage!.pending_bytes, 0);
    offline = false;
    await evidenceWorker(f.root, true, { scheduleRetry: () => {} });
    const m = readManifest(f.root, source)!;
    assert.equal(m.coverage!.pending_bytes, 0);
    assert.equal(uploadedBytes, readFileSync(source.path).length);
    assert.deepEqual(reconstruct(f.root, source, m), readFileSync(source.path));
    assert.equal(m.journal_links.length, 1);
    assert.ok(revision >= 1);
  } finally {
    if (oldClaude === undefined) delete process.env.CLAUDE_CONFIG_DIR;
    else process.env.CLAUDE_CONFIG_DIR = oldClaude;
    if (oldXdg === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = oldXdg;
    await remote.close();
    f.cleanup();
  }
});
test("final checkpoint detects an unsampled prefix rewrite followed by append", async () => {
  const f = fixture();
  try {
    const original = Buffer.concat([
      line("a", "x".repeat(15000)),
      line("b", "z".repeat(15000)),
    ]);
    writeFileSync(f.source.path, original);
    await captureSource(f.root, "folder", f.source, { producer: "test" });
    const rewritten = Buffer.from(original);
    rewritten[10000] = 89;
    const current = Buffer.concat([rewritten, line("c")]);
    writeFileSync(f.source.path, current);
    const m = await captureSource(f.root, "folder", f.source, {
      producer: "test",
      verifyPrefix: true,
    });
    assert.deepEqual(reconstruct(f.root, f.source, m, 1), original);
    assert.deepEqual(reconstruct(f.root, f.source, m, 2), current);
  } finally {
    f.cleanup();
  }
});
test("installation upload limiter permits at most four simultaneous processes", async () => {
  const f = fixture(),
    log = join(f.root, "slots.log");
  const moduleUrl = new URL("./agent-evidence-sync.js", import.meta.url).href;
  const code = `import {withEvidenceUploadSlot} from ${JSON.stringify(moduleUrl)};import {appendFileSync} from 'node:fs';await withEvidenceUploadSlot(async()=>{appendFileSync(process.env.SLOT_LOG,'start\\n');await new Promise(r=>setTimeout(r,100));appendFileSync(process.env.SLOT_LOG,'end\\n');});`;
  try {
    await Promise.all(
      Array.from(
        { length: 9 },
        () =>
          new Promise<void>((resolve, reject) => {
            const child = spawn(
              process.execPath,
              ["--input-type=module", "-e", code],
              {
                env: {
                  ...process.env,
                  XDG_CONFIG_HOME: join(f.root, "config"),
                  SLOT_LOG: log,
                },
                stdio: "ignore",
              },
            );
            child.on("error", reject);
            child.on("exit", (n) =>
              n === 0 ? resolve() : reject(new Error(`slot child ${n}`)),
            );
          }),
      ),
    );
    let active = 0,
      maximum = 0;
    for (const entry of readFileSync(log, "utf8").trim().split("\n")) {
      active += entry === "start" ? 1 : -1;
      maximum = Math.max(maximum, active);
      assert.ok(active <= 4);
    }
    assert.equal(active, 0);
    assert.ok(maximum > 1);
  } finally {
    f.cleanup();
  }
});
test("Codex Stop without transcript path is consumed when it arrives during upload", async () => {
  const f = fixture(),
    oldHome = process.env.CODEX_HOME,
    oldConfig = process.env.XDG_CONFIG_HOME;
  const home = join(f.root, "codex-home");
  process.env.CODEX_HOME = home;
  process.env.XDG_CONFIG_HOME = join(f.root, "config");
  const native = join(home, "sessions", "native.jsonl");
  mkdirSync(join(home, "sessions"), { recursive: true });
  const source: Source = { ...f.source, agent: "codex", path: native };
  let injected = false,
    revision = 0;
  const aliases: string[] = [];
  const remote = await server(async (req, res, bytes) => {
    res.setHeader("Content-Type", "application/json");
    if (req.url!.endsWith("/capabilities")) {
      if (!injected) {
        injected = true;
        assert.equal(
          await dispatchEvidence(f.root, "codex", {
            session_id: "parent",
            hook_event_name: "Stop",
          }),
          f.root,
        );
      }
      res.end(
        JSON.stringify({
          enabled: true,
          schema: 1,
          max_object_bytes: 67108864,
          max_batch_objects: 256,
        }),
      );
      return;
    }
    if (req.method === "PUT") {
      res.end("{}");
      return;
    }
    if (req.url!.endsWith("/batches")) {
      const body = JSON.parse(bytes.toString());
      aliases.push(
        ...body.journal_links.map(
          (l: { journal_entry_id: string }) => l.journal_entry_id,
        ),
      );
      res.end(
        JSON.stringify({
          session_id: "race-id",
          revision,
          missing_objects: body.objects.map((o: { id: string }) => o.id),
        }),
      );
      return;
    }
    res.end(
      JSON.stringify({
        status: "accepted",
        session_id: "race-id",
        revision: ++revision,
        index_status: "pending",
      }),
    );
  });
  try {
    config(f.root, remote.url);
    writeFileSync(
      native,
      [
        JSON.stringify({ type: "session_meta", payload: { id: "parent" } }),
        "",
        JSON.stringify({ type: "future" }),
        JSON.stringify({
          type: "event_msg",
          payload: {
            type: "user_message",
            message: "Native user without an id",
          },
        }),
        JSON.stringify({
          type: "event_msg",
          payload: { type: "agent_message", message: "Native assistant" },
        }),
        "",
      ].join("\n"),
    );
    const turn = parseTurn("codex", {
      session_id: "parent",
      transcript_path: native,
    })!;
    assert.equal(turn.turnId, "3");
    await dispatchEvidence(f.root, "codex", {
      session_id: "parent",
      transcript_path: native,
      hook_event_name: "SessionStart",
    });
    await evidenceWorker(f.root, true, { scheduleRetry: () => {} });
    assert.ok(injected);
    assert.ok(aliases.includes(`codex:parent:${turn.turnId}`));
    assert.equal(
      readManifest(f.root, source)!.journal_links[0].journal_entry_id,
      `codex:parent:${turn.turnId}`,
    );
    assert.equal(
      readdirSync(join(f.root, ".kioku/memory/.evidence-state/pending")).length,
      0,
    );
  } finally {
    if (oldHome === undefined) delete process.env.CODEX_HOME;
    else process.env.CODEX_HOME = oldHome;
    if (oldConfig === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = oldConfig;
    await remote.close();
    f.cleanup();
  }
});
test("storage PUT timeout exceeds control timeout while respecting worker deadline", () => {
  assert.equal(evidenceRequestTimeout("POST", 180000), 30000);
  assert.equal(evidenceRequestTimeout("PUT", 180000), 120000);
  assert.equal(evidenceRequestTimeout("PUT", 45000), 45000);
});
test("detached worker retries a transient outage without another agent hook", async () => {
  const f = fixture(),
    oldHome = process.env.CODEX_HOME,
    oldConfig = process.env.XDG_CONFIG_HOME;
  const home = join(f.root, "codex-home");
  process.env.CODEX_HOME = home;
  process.env.XDG_CONFIG_HOME = join(f.root, "config");
  mkdirSync(join(home, "sessions"), { recursive: true });
  const source: Source = {
    ...f.source,
    agent: "codex",
    path: join(home, "sessions", "retry.jsonl"),
  };
  let retryPid: number | undefined;
  let capabilities = 0,
    commits = 0;
  const remote = await server((req, res, bytes) => {
    res.setHeader("Content-Type", "application/json");
    if (req.url!.endsWith("/capabilities")) {
      if (++capabilities <= 3) {
        res.statusCode = 503;
        res.end("{}");
      } else
        res.end(
          JSON.stringify({
            enabled: true,
            schema: 1,
            max_object_bytes: 67108864,
            max_batch_objects: 256,
          }),
        );
      return;
    }
    if (req.method === "PUT") {
      res.end("{}");
      return;
    }
    if (req.url!.endsWith("/batches")) {
      const b = JSON.parse(bytes.toString());
      res.end(
        JSON.stringify({
          session_id: "automatic-retry",
          revision: commits,
          missing_objects: b.objects.map((o: { id: string }) => o.id),
        }),
      );
      return;
    }
    res.end(
      JSON.stringify({
        status: "accepted",
        session_id: "automatic-retry",
        revision: ++commits,
        index_status: "pending",
      }),
    );
  });
  try {
    config(f.root, remote.url);
    writeFileSync(
      source.path,
      JSON.stringify({
        type: "event_msg",
        payload: { type: "user_message", message: "No future hook" },
      }) + "\n",
    );
    await dispatchEvidence(f.root, "codex", {
      session_id: "parent",
      transcript_path: source.path,
      hook_event_name: "Stop",
    });
    const child = spawn(
      process.execPath,
      [
        fileURLToPath(new URL("../index.js", import.meta.url)),
        "evidence-worker",
        "--root",
        f.root,
      ],
      { env: process.env, stdio: "ignore" },
    );
    await new Promise<void>((resolve, reject) => {
      child.on("error", reject);
      child.on("exit", (n) =>
        n === 0 ? resolve() : reject(new Error(`worker ${n}`)),
      );
    });
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      try {
        retryPid = Number(
          readFileSync(
            join(
              f.root,
              ".kioku/memory/.evidence-state/scheduled-retry.lock/owner",
            ),
            "utf8",
          ).split(":")[0],
        );
      } catch {
        /* timer already finished */
      }
      const sync = readJson<{ manifest_hash?: string }>(
        join(sessionDir(f.root, source), ".sync.json"),
        {},
      );
      const m = readManifest(f.root, source);
      if (m && sync.manifest_hash === hash(JSON.stringify(m))) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    assert.ok(capabilities >= 4);
    assert.equal(commits, 1);
    const m = readManifest(f.root, source)!;
    assert.equal(
      readJson<{ manifest_hash?: string }>(
        join(sessionDir(f.root, source), ".sync.json"),
        {},
      ).manifest_hash,
      hash(JSON.stringify(m)),
    );
    assert.equal(m.journal_links[0].journal_entry_id, "codex:parent:0");
  } finally {
    if (retryPid) {
      try {
        process.kill(retryPid, "SIGTERM");
      } catch {
        /* already exited */
      }
    }
    if (oldHome === undefined) delete process.env.CODEX_HOME;
    else process.env.CODEX_HOME = oldHome;
    if (oldConfig === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = oldConfig;
    await remote.close();
    f.cleanup();
  }
});
test("slow storage acknowledgement outlives the control timeout and still commits", async () => {
  const f = fixture(),
    originalTimeout = AbortSignal.timeout;
  let commits = 0;
  const timeouts: number[] = [];
  // Scale real timers 1000x so this exercises timeout/abort behavior in milliseconds.
  AbortSignal.timeout = (milliseconds: number) => {
    timeouts.push(milliseconds);
    return originalTimeout.call(
      AbortSignal,
      Math.max(1, Math.ceil(milliseconds / 1000)),
    );
  };
  const remote = await server((req, res, bytes) => {
    res.setHeader("Content-Type", "application/json");
    if (req.url!.endsWith("/capabilities")) {
      res.end(
        JSON.stringify({
          enabled: true,
          schema: 1,
          max_object_bytes: 67108864,
          max_batch_objects: 256,
        }),
      );
      return;
    }
    if (req.method === "PUT") {
      setTimeout(() => res.end("{}"), 55);
      return;
    }
    if (req.url!.endsWith("/batches")) {
      const b = JSON.parse(bytes.toString());
      res.end(
        JSON.stringify({
          session_id: "slow",
          revision: 0,
          missing_objects: b.objects.map((o: { id: string }) => o.id),
        }),
      );
      return;
    }
    commits++;
    res.end(
      JSON.stringify({
        status: "accepted",
        session_id: "slow",
        revision: 1,
        index_status: "pending",
      }),
    );
  });
  try {
    config(f.root, remote.url);
    writeFileSync(f.source.path, line("slow"));
    const m = await captureSource(f.root, "folder", f.source, {
      producer: "test",
    });
    await syncEvidence(
      f.root,
      "folder",
      f.source,
      m,
      true,
      Date.now() + 120000,
    );
    assert.equal(commits, 1);
    assert.ok(timeouts.some((ms) => ms > 30000));
    assert.deepEqual(reconstruct(f.root, f.source, m), line("slow"));
  } finally {
    AbortSignal.timeout = originalTimeout;
    await remote.close();
    f.cleanup();
  }
});
test("permanent authorization failures keep the outbox without autonomous retry", async () => {
  const f = fixture(),
    oldHome = process.env.CODEX_HOME,
    oldConfig = process.env.XDG_CONFIG_HOME;
  process.env.CODEX_HOME = join(f.root, "home");
  process.env.XDG_CONFIG_HOME = join(f.root, "config");
  mkdirSync(join(process.env.CODEX_HOME, "sessions"), { recursive: true });
  const path = join(process.env.CODEX_HOME, "sessions", "denied.jsonl");
  let requests = 0;
  const scheduled: number[] = [];
  const remote = await server((_req, res) => {
    requests++;
    res.statusCode = 403;
    res.end("{}");
  });
  try {
    config(f.root, remote.url);
    writeFileSync(
      path,
      JSON.stringify({
        type: "event_msg",
        payload: { type: "user_message", message: "Denied" },
      }) + "\n",
    );
    await dispatchEvidence(f.root, "codex", {
      session_id: "denied",
      transcript_path: path,
      hook_event_name: "Stop",
    });
    await evidenceWorker(f.root, true, {
      scheduleRetry: (_root, at) => scheduled.push(at),
    });
    assert.equal(requests, 1);
    assert.deepEqual(scheduled, []);
    assert.equal(
      readdirSync(join(f.root, ".kioku/memory/.evidence-state/pending")).length,
      1,
    );
  } finally {
    if (oldHome === undefined) delete process.env.CODEX_HOME;
    else process.env.CODEX_HOME = oldHome;
    if (oldConfig === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = oldConfig;
    await remote.close();
    f.cleanup();
  }
});
