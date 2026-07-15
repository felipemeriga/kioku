import kleur from "kleur";
import { readConfig } from "../lib/config.js";
import { whoami as whoamiApi } from "../lib/api.js";
import { panel } from "../ui/panel.js";

interface Opts {
  json?: boolean;
}

export async function whoami(opts: Opts): Promise<void> {
  const cfg = readConfig();
  if (!cfg.access_token || !cfg.email) {
    if (opts.json) console.log(JSON.stringify({ signed_in: false }, null, 2));
    else console.log(kleur.yellow("Not signed in.") + " " + kleur.dim("Run: kioku login"));
    process.exitCode = 1;
    return;
  }
  const w = await whoamiApi();
  if (opts.json) {
    console.log(
      JSON.stringify(
        {
          signed_in: true,
          email: cfg.email,
          user_id: w.user_id,
          root_folders: w.root_folders.length,
          api_base: cfg.api_base,
        },
        null,
        2,
      ),
    );
    return;
  }
  console.log(panel({
    title: "You",
    body: [`Email    ${cfg.email}`, `User id  ${w.user_id}`, `Folders  ${w.root_folders.length}`].join("\n"),
  }));
}
