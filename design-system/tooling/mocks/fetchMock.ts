// Routes the app's /api/* calls to demo fixtures so every component renders offline.
import * as F from "./fixtures";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

function sseChat(): Response {
  const enc = new TextEncoder();
  const answer =
    "Kioku keeps a **briefing** per repo folder — overview, architecture, important files and more — refreshed by the watcher after each push.\n\nAsk it anything about the repo and it cites the files it used.";
  const tokens = answer.match(/.{1,6}/gs) || [];
  const stream = new ReadableStream({
    async start(ctrl) {
      const send = (o: unknown) => ctrl.enqueue(enc.encode(`data: ${JSON.stringify(o)}\n`));
      for (const stage of ["thinking", "searching", "analyzing", "generating"]) {
        send({ stage, docs: stage === "searching" ? 8 : undefined });
        await delay(500);
      }
      for (const t of tokens) {
        send({ token: t });
        await delay(25);
      }
      send({ done: true });
      ctrl.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}

async function route(url: URL, init?: RequestInit): Promise<Response> {
  const p = url.pathname;
  const q = url.searchParams;
  const method = (init?.method || "GET").toUpperCase();
  await delay(120);

  if (p === "/api/chat") return sseChat();
  if (p === "/api/conversations") return method === "POST" ? json({ id: "c-new", title: "New conversation", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) : json(F.conversations);
  let m = p.match(/^\/api\/conversations\/([^/]+)$/);
  if (m) {
    const c = F.conversations.find((x) => x.id === m![1]) || F.conversations[0];
    return json({ ...c, messages: m[1] === "c-new" ? [] : F.messages });
  }
  if (p === "/api/folders") {
    const parent = q.get("parent_id");
    if (method === "POST") return json({ id: "f-new", name: "New folder", parent_id: parent, user_id: "u-demo", created_at: new Date().toISOString(), kind: "folder" });
    return json(F.folders.filter((f) => f.parent_id === (parent || null)));
  }
  m = p.match(/^\/api\/folders\/([^/]+)\/breadcrumbs$/);
  if (m) {
    const chain = [];
    let cur = F.folders.find((f) => f.id === m![1]);
    while (cur) {
      chain.unshift({ id: cur.id, name: cur.name, kind: cur.kind });
      cur = F.folders.find((f) => f.id === cur!.parent_id);
    }
    return json(chain);
  }
  m = p.match(/^\/api\/folders\/([^/]+)\/briefing/);
  if (m) {
    if (p.includes("/section/")) return json({ ok: true, section: F.briefing.sections.overview });
    const f = F.folders.find((x) => x.id === m![1]);
    return json({ ...F.briefing, folder: { id: m[1], name: f?.name ?? "kioku", kind: "repo" } });
  }
  if (/^\/api\/folders\/[^/]+\/documentation$/.test(p)) return json(F.documentation);
  if (/^\/api\/folders\/[^/]+$/.test(p)) return json({ ok: true });
  if (p === "/api/documents") {
    const fid = q.get("folder_id");
    return json(fid ? F.documents.filter((d) => d.folder_id === fid) : F.documents);
  }
  if (p === "/api/documents/filters") return json(F.filters);
  if (p === "/api/documents/ingestion-status") return json(F.ingestionTasks);
  if (p === "/api/documents/upload") return json({ task_id: "t-new" });
  m = p.match(/^\/api\/documents\/(.+)\/content$/);
  if (m) return json(F.documentContent(decodeURIComponent(m[1])));
  if (/\/download$/.test(p)) return json({ url: "#" });
  if (p.startsWith("/api/documents/")) return json({ ok: true });
  if (p === "/api/api-keys") return method === "POST" ? json({ ...F.apiKeys[0], id: "k-new", key: "kio_live_9f2c…e41a" }) : json(F.apiKeys);
  if (p.startsWith("/api/api-keys/")) return json({ ok: true });
  if (p === "/api/ingestion-jobs") return json([F.notionJob]);
  if (p.startsWith("/api/ingestion-jobs/")) return json(F.notionJob);
  if (p === "/api/notion/configs") return method === "POST" ? json(F.notionConfig) : json([F.notionConfig]);
  if (/\/pending$/.test(p)) return json({ total_in_notion: 41, total_synced: 38, pending: [{ page_id: "p-9", title: "Incident review — Aug", reason: "missing" }, { page_id: "p-4", title: "On-call handbook", reason: "outdated" }] });
  if (/^\/api\/notion\/configs\/[^/]+\/(sync|reconcile)$/.test(p)) return json({ job_id: "j-1", already_running: false });
  if (p.startsWith("/api/notion/configs/")) return json({ ok: true });
  if (p === "/api/notion/pages") return json([{ id: "pg-1", title: "Engineering Wiki" }, { id: "pg-2", title: "Product specs" }]);
  if (p === "/api/mem0/status") {
    const f = F.folders.find((x) => x.id === q.get("root_folder_id"));
    return json(f?.kind === "repo" ? { available: true, healthy: true, error: null } : { available: false, reason: "not a repo folder" });
  }
  if (p === "/api/mem0/memories/rules") return json({ rules: F.memoriesRules });
  if (p === "/api/mem0/memories/recent") return json({ memories: F.memoriesRecent });
  if (p.startsWith("/api/mem0/memories")) return json({ ok: true, metadata: {} });
  if (p === "/api/github/repos") return json(F.githubRepos);
  if (p === "/api/cli/auth/device/info") return json({ hostname: "felipes-macbook-air", os: "darwin", valid: true, expired: false });
  if (p.startsWith("/api/cli/auth/device/")) return json({ ok: true });
  return json({ detail: `demo: no fixture for ${p}` }, 404);
}

const realFetch = window.fetch.bind(window);
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(raw, window.location.href);
  if (url.pathname.startsWith("/api/")) return route(url, init);
  return realFetch(input, init);
};
