import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";

const run = (args: string[], env: Record<string, string> = {}) =>
  execFileSync(process.execPath, ["scripts/deploy-prod.mjs", ...args], {
    cwd: process.cwd(),
    env: { ...process.env, ...env },
    stdio: "pipe",
  }).toString();

describe("production deploy", () => {
  it("stages the site without a wrangler.toml so dashboard bindings survive", () => {
    const out = run(["--dry-run"]);
    expect(out).toContain("staged functions, public, src");
    expect(out).toContain("no wrangler.toml");
    expect(out).toContain("dry run: would deploy to jobagent-companion");
  });

  it("refuses to deploy a dev project", () => {
    expect(() => run(["--dry-run"], { CF_PAGES_PROJECT: "jobagent-companion-dev" })).toThrow();
  });
});
