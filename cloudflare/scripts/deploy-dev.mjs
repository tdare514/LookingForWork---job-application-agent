import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";

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
  stdio: "inherit",
});
if (check.status !== 0) process.exit(check.status ?? 1);

const deploy = spawnSync(
  "npx",
  [
    "wrangler",
    "pages",
    "deploy",
    "public",
    "--project-name",
    projectName,
    "--branch",
    "dev",
    "--config",
    configPath,
  ],
  { stdio: "inherit" },
);
process.exit(deploy.status ?? 1);
