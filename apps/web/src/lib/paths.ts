/** Resolve a relative markdown link (href) against the linking document's path. */
export function resolveLink(fromPath: string, href: string): string {
  const clean = href.split("#")[0];
  const baseParts = fromPath.split("/").slice(0, -1);
  const parts = clean.split("/");
  const stack = [...baseParts];
  for (const p of parts) {
    if (p === "." || p === "") continue;
    if (p === "..") stack.pop();
    else stack.push(p);
  }
  return stack.join("/");
}
