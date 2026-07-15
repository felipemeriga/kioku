/** Only allow same-origin relative paths: must start with a single "/"
 *  and not be protocol-relative ("//…") or contain a scheme ("://"). */
export function safeRedirect(param: string | null): string {
  if (!param) return "/";
  if (!param.startsWith("/")) return "/";
  if (param.startsWith("//")) return "/";
  if (param.includes("://")) return "/";
  return param;
}
