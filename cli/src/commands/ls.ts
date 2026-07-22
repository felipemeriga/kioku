/**
 * `kioku ls [path]` — browse your workspace.
 *
 * With no arg → list root folders.
 * With a name/path → list that folder's children.
 * With --json → machine-readable output.
 */

import kleur from "kleur";
import { listChildren, listRootFolders, whoami } from "../lib/api.js";
import { section, info } from "../lib/banner.js";
import { renderTable } from "../ui/table.js";
import { sym } from "../ui/theme.js";

interface Opts {
  json?: boolean;
}

interface Entry {
  id: string;
  name: string;
  kind: "folder" | "repo";
  parent_id: string | null;
}

export async function ls(pathArg: string | undefined, opts: Opts): Promise<void> {
  const path = (pathArg ?? "").trim();

  // 1. No path → list roots.
  if (!path) {
    const w = await whoami();
    const roots: Entry[] = w.root_folders.map((f) => ({
      id: f.id,
      name: f.name,
      kind: f.kind ?? "folder",
      parent_id: null,
    }));
    if (opts.json) {
      console.log(JSON.stringify(roots, null, 2));
      return;
    }
    printListing(`Signed in as ${w.user_id.slice(0, 8)}… · roots`, roots);
    if (roots.length === 0) {
      console.log();
      info("No roots yet. Run kioku init in a repo to create one.");
    }
    return;
  }

  // 2. Resolve the path.
  const parts = path.split("/").filter(Boolean);
  const roots = await listRootFolders();
  let current = roots.find(
    (f) => f.name.toLowerCase() === parts[0].toLowerCase() || f.id === parts[0],
  );
  if (!current) {
    throw new Error(`No folder found for "${path}"`);
  }
  for (let i = 1; i < parts.length; i += 1) {
    const kids = await listChildren(current.id);
    const next = kids.find(
      (f) => f.name.toLowerCase() === parts[i].toLowerCase() || f.id === parts[i],
    );
    if (!next) {
      throw new Error(
        `Under "${current.name}", no child named "${parts[i]}"`,
      );
    }
    current = next;
  }

  const children = await listChildren(current.id);
  const entries: Entry[] = children.map((f) => ({
    id: f.id,
    name: f.name,
    kind: (f.kind as "folder" | "repo") ?? "folder",
    parent_id: current!.id,
  }));

  if (opts.json) {
    console.log(JSON.stringify({
      path,
      folder_id: current.id,
      folder_kind: current.kind ?? "folder",
      children: entries,
    }, null, 2));
    return;
  }

  const header = `${path}  ${kleur.dim(
    "(" + current.kind + " · " + current.id.slice(0, 8) + "…)",
  )}`;
  printListing(header, entries);
  if (entries.length === 0) {
    console.log();
    info("Empty. `kioku init` in a repo to add one here.");
  }
}

function printListing(header: string, entries: Entry[]): void {
  section(header);
  if (entries.length === 0) return;
  const rows = entries.map((e) => [
    e.kind === "repo" ? `${sym.repo} ${e.name}` : `${sym.folder} ${e.name}`,
    e.kind,
    e.id.slice(0, 8),
  ]);
  console.log(renderTable(["Name", "Kind", "Id"], rows));
  console.log();
}
