import { strict as assert } from "node:assert";
import { cliInvocation, shQuote } from "../../cli/src/lib/claude.js";
assert.equal(cliInvocation(), shQuote(process.execPath));
console.log("Standalone hook invocation uses the executable directly");
