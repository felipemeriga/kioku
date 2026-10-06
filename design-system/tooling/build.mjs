// Builds design-system/components/bundle.js (window.Kioku) from frontend/src,
// with /api and Supabase mocked so every component renders offline.
// Usage: (cd frontend && npm ci) && (cd design-system/tooling && npm ci && npm run build)
import * as esbuild from "esbuild";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "../..");
const APP = path.join(REPO, "frontend/src");
const NM = path.join(REPO, "frontend/node_modules");
const OUT = path.resolve(HERE, "../components");
const S = path.join(HERE, "shims");
const tsx = (p) => [".tsx", ".ts"].map((e) => p + e).find((f) => fs.existsSync(f)) || p;
const plugin = {
  name: "kioku-ds",
  setup(b) {
    const map = { "react": "react.js", "react-dom": "react-dom.js", "react-dom/client": "react-dom-client.js", "react/jsx-runtime": "jsx-runtime.js", "react/jsx-dev-runtime": "jsx-runtime.js" };
    b.onResolve({ filter: /^react(-dom)?(\/.*)?$/ }, (a) => map[a.path] ? { path: path.join(S, map[a.path]) } : undefined);
    b.onResolve({ filter: /^react-syntax-highlighter$/ }, () => ({ path: path.join(S, "highlighter.ts") }));
    b.onResolve({ filter: /^@app\// }, (a) => ({ path: tsx(path.join(APP, a.path.slice(5))) }));
    b.onResolve({ filter: /^\.{1,2}\/(lib\/)?supabase$/ }, (a) => a.importer.startsWith(APP) ? { path: path.join(HERE, "mocks/supabase.ts") } : undefined);
  },
};
await esbuild.build({
  entryPoints: [path.join(HERE, "entry.tsx")], bundle: true, format: "iife", minify: true, target: "es2020",
  outfile: path.join(OUT, "bundle.js"), nodePaths: [NM], jsx: "automatic", plugins: [plugin], conditions: ["production"],
  define: { "process.env.NODE_ENV": '"production"', "import.meta.env.VITE_SUPABASE_URL": '"https://demo.supabase.co"', "import.meta.env.VITE_SUPABASE_ANON_KEY": '"demo"' },
  legalComments: "none", logLevel: "warning",
});
const comps = fs.readdirSync(OUT).filter((d) => fs.existsSync(path.join(OUT, d, "README.md")));
let js = fs.readFileSync(path.join(OUT, "bundle.js"), "utf8").replace(/<\/script/gi, "<\\/script").replace(/<!--/g, "\\x3C!--");
const header = `/* @ds-bundle: ${JSON.stringify({ format: 4, namespace: "Kioku", components: comps.map((name) => ({ name })) })} */\n`;
fs.writeFileSync(path.join(OUT, "bundle.js"), header + js);
// React 18 UMD builds the previews load before bundle.js
fs.mkdirSync(path.join(OUT, "lib"), { recursive: true });
for (const [pkg, f] of [["react", "react.production.min.js"], ["react-dom", "react-dom.production.min.js"]])
  fs.copyFileSync(path.join(HERE, "node_modules", pkg, "umd", f), path.join(OUT, "lib", f));
console.log(`bundle.js ${(fs.statSync(path.join(OUT, "bundle.js")).size / 1024).toFixed(0)} KB · ${comps.length} components`);
