// Internal service entry point. kioku init installs and starts it automatically.
import { readFileSync } from "node:fs";
import { runManabi, type ManabiConnection } from "./lib/manabi-client.js";

const configPath = process.argv[2];
if (!configPath) throw new Error("Missing Manabi configuration path");
const controller = new AbortController();
process.once("SIGTERM", () => controller.abort());
process.once("SIGINT", () => controller.abort());
await runManabi({
  signal: controller.signal,
  readConnection: () => {
    try {
      return JSON.parse(readFileSync(configPath, "utf8")) as ManabiConnection;
    } catch {
      return null;
    }
  },
  log: (message) => console.log(`${new Date().toISOString()} ${message}`),
});
