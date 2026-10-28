import { strict as assert } from "node:assert";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { supplementTopLevelCalls } from "./graph-call-edges.js";

test("indexes top-level TypeScript initializer calls that Graphify omits", () => {
  const dir = mkdtempSync(join(tmpdir(), "kioku-graph-"));
  try {
    writeFileSync(
      join(dir, "sample.ts"),
      "function sample() {}\nconst cached = sample();\nfunction wrapper() { sample(); }\n",
    );
    const nodes = [
      { id: "file", label: "sample.ts", source_file: "sample.ts" },
      { id: "fn", label: "sample()", source_file: "sample.ts" },
      { id: "cached", label: "cached", source_file: "sample.ts" },
      { id: "wrapper", label: "wrapper()", source_file: "sample.ts" },
    ];
    const edges = [
      {
        source: "wrapper",
        target: "fn",
        relation: "calls",
        source_file: "sample.ts",
        source_location: "L3",
      },
    ];
    assert.deepEqual(
      supplementTopLevelCalls(dir, nodes, edges).map(
        ({ source, target, source_location }) => [
          source,
          target,
          source_location,
        ],
      ),
      [["cached", "fn", "L2"]],
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
