import { test } from "node:test";
import assert from "node:assert/strict";
import { mcpUrlToRestBase, restBaseToMcpBase, restBaseToWebUrl } from "./urls.js";

test("mcpUrlToRestBase — dev port swap", () => {
  assert.equal(mcpUrlToRestBase("http://localhost:8001/sse"), "http://localhost:8000");
});

test("mcpUrlToRestBase — prod subdomain swap", () => {
  assert.equal(
    mcpUrlToRestBase("https://kioku.mcp.merigafy.com/sse"),
    "https://kioku.api.merigafy.com"
  );
  assert.equal(mcpUrlToRestBase("https://mcp.example.com/sse"), "https://api.example.com");
});

test("restBaseToMcpBase — dev + prod", () => {
  assert.equal(restBaseToMcpBase("http://localhost:8000"), "http://localhost:8001");
  assert.equal(
    restBaseToMcpBase("https://kioku.api.merigafy.com"),
    "https://kioku.mcp.merigafy.com"
  );
});

test("restBaseToWebUrl — dev + prod", () => {
  assert.equal(restBaseToWebUrl("http://localhost:8000"), "http://localhost:5174");
  assert.equal(restBaseToWebUrl("https://kioku.api.merigafy.com"), "https://kioku.merigafy.com");
  assert.equal(restBaseToWebUrl("https://api.example.com"), "https://example.com");
});
