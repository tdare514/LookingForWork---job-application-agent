import { spawnSync } from "node:child_process";
import { cp, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const projectName = process.env.CF_DEV_PAGES_PROJECT;
const databaseId = process.env.CF_DEV_D1_DATABASE_ID;
const configPath = process.env.CF_DEV_WRANGLER_CONFIG ?? "wrangler.dev.toml";

if (projectName !== "jobagent-companion-dev") {
  console.error(
    'Dev deployment refused: CF_DEV_PAGES_PROJECT must be exactly "jobagent-companion-dev".',
  );
  process.exit(1);
}

if (!/^[0-9a-f-]{36}$/i.test(databaseId ?? "")) {
  console.error(
    "Dev deployment refused: CF_DEV_D1_DATABASE_ID must be a remote D1 UUID.",
  );
  process.exit(1);
}

const config = await readFile(configPath, "utf8").catch(() => null);
if (
  config === null ||
  !config.includes('FREE_TIER_ENABLED = "true"') ||
  !config.includes('ACCOUNT_PLAN = "free"') ||
  !config.includes(`database_id = "${databaseId}"`) ||
  /(^|\n)\s*(workers_ai|ai|queues|pipelines|analytics_engine|vectorize|r2)\b/i.test(config)
) {
  console.error(
    "Dev deployment refused: missing free-tier settings, wrong D1 id, or a paid feature in Wrangler config.",
  );
  process.exit(1);
}

const check = spawnSync(process.execPath, ["scripts/verify-free-plan.mjs"], {
  env: {
    ...process.env,
    FREE_TIER_ENABLED: "true",
    ACCOUNT_PLAN: "free",
  },
  stdio: "inherit",
});
if (check.status !== 0) process.exit(check.status ?? 1);

const stagingDir = await mkdtemp(join(tmpdir(), "jobagent-pages-deploy-"));
try {
  await cp("public", join(stagingDir, "public"), { recursive: true });
  await cp("functions", join(stagingDir, "functions"), { recursive: true });
  await cp(configPath, join(stagingDir, "wrangler.toml"));

  // Pages rejects --config when it points at a custom path. Staging the
  // validated config at the default name keeps the D1 binding in the deploy.
  const deploy = spawnSync(
    "npx",
    ["wrangler", "pages", "deploy", "public", "--project-name", projectName, "--branch", "dev"],
    { cwd: stagingDir, stdio: "inherit" },
  );
  process.exitCode = deploy.status ?? 1;
} finally {
  await rm(stagingDir, { recursive: true, force: true });
}
