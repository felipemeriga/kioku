const languages: Record<string, string> = {
  rs: "rust",
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  go: "go",
  java: "java",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  cs: "csharp",
  json: "json",
  yml: "yaml",
  yaml: "yaml",
  toml: "toml",
  sql: "sql",
  sh: "bash",
  bash: "bash",
  ps1: "powershell",
  rb: "ruby",
  proto: "protobuf",
  xml: "markup",
  html: "markup",
  css: "css",
  scss: "scss",
  md: "markdown",
  hpp: "cpp",
  mjs: "javascript",
  cjs: "javascript",
};

export function codeLanguage(filename: string): string | undefined {
  const extension = filename
    .toLowerCase()
    .match(/\.([a-z0-9]+)(?=$|[:\s\]])/)?.[1];
  return extension ? languages[extension] : undefined;
}
