// Internal Node service entry point; standalone builds use the hidden CLI command.
import { runManabiDaemon } from "./lib/manabi-client.js";
await runManabiDaemon(process.argv[2]);
