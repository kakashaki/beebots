// 29 Oct 2026 audit: the default install served plain HTTP, so the owner password and API keys crossed the network in
// the clear. These pin the deploy files to HTTPS by default. (`caddy validate` checks the syntax; it is not in CI.)
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const caddyfile = readFileSync(new URL("../Caddyfile", import.meta.url), "utf8");
const compose = readFileSync(new URL("../docker-compose.yml", import.meta.url), "utf8");

/** The body of the top-level block whose address line is `address {`. */
function block(address: string): string {
  const start = caddyfile.indexOf(`\n${address} {\n`);
  expect(start, `no "${address}" block`).toBeGreaterThanOrEqual(0);
  const end = caddyfile.indexOf("\n}\n", start + 1);
  return caddyfile.slice(start, end);
}

describe("deploy: HTTPS by default", () => {
  it("compose never defaults Caddy's site address to plain HTTP", () => {
    const line = compose.split("\n").find((l) => l.trim().startsWith("SITE_ADDRESS:"));
    expect(line).toBeDefined();
    expect(line).not.toMatch(/:80\b|http:\/\//);
    expect(line).toContain("${PUBLIC_DOMAIN:-localhost}");
  });

  it("with no domain, the server's IP gets HTTPS from Caddy's internal authority", () => {
    const any443 = block(":443");
    expect(any443).toMatch(/tls internal \{\s*on_demand\s*\}/);
    expect(any443).toContain("import beebots");
  });

  it("plain HTTP only redirects, except the Zap's public scorecard and signed lab door", () => {
    const http = block("http://");
    expect(http).not.toContain("import beebots");
    expect(http).toContain("redir https://{host}{uri} permanent");
    const paths = [...http.matchAll(/^\s*path (.+)$/gm)].map((m) => m[1]!.trim());
    expect(paths).toEqual(["/keeper/scorecard", "/lab/*"]);
    expect(http).not.toMatch(/\/setup|\/hive|\/keeper\/(connect|round|rollback|disconnect)/);
  });

  it("Caddy trusts no proxy, so a client cannot choose its own X-Forwarded-For", () => {
    expect(caddyfile).not.toMatch(/trusted_proxies/);
  });
});
