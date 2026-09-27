// Deploy the phone page and its Functions to the production Pages project.
//
// The checked-in wrangler.toml is for local development only: its D1
// database_id is a placeholder. A Pages deploy that sees a wrangler.toml
// treats it as the source of bindings and would replace the real D1 binding
// set in the dashboard. So this stages public/, functions/ and src/ in a
// temporary directory with no config at all, and deploys from there. Bindings,
// secrets and compatibility settings stay whatever the dashboard says.
//
// It uploads whatever is in public/, including snapshot.json when present
// (ADR 0009): the production project sits behind Cloudflare Access. It never
// creates resources, sets secrets or touches the dev project.
//
//   npm run deploy:prod             deploy
//   npm run deploy:prod -- --dry-run   stage and list, deploy nothing
import { spawnSync } from "node:child_process";
import { access, cp, mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const projectName = process.env.CF_PAGES_PROJECT ?? "jobagent-companion";
const dryRun = process.argv.includes("--dry-run");

if (projectName.endsWith("-dev")) {
  console.error(`Refused: ${projectName} is a dev project; use npm run deploy:dev.`);
  process.exit(1);
}

// The staging directory has no node_modules, so a bare `npx wrangler` there
// would fetch whatever version is current. Run the one package-lock.json pins.
const wrangler = resolve("node_modules", ".bin", "wrangler");
if (!(await access(wrangler).then(() => true, () => false))) {
  console.error("Refused: run `npm ci` first so the locked wrangler is used.");
  process.exit(1);
}

const stagingDir = await mkdtemp(join(tmpdir(), "jobagent-pages-prod-"));
try {
  for (const dir of ["public", "functions", "src"]) {
    await cp(dir, join(stagingDir, dir), { recursive: true });
  }
  const staged = (await readdir(stagingDir)).sort();
  if (staged.includes("wrangler.toml")) {
    console.error("Refused: a wrangler.toml reached the staging directory.");
    process.exit(1);
  }
  console.log(`staged ${staged.join(", ")}; no wrangler.toml, bindings stay as the dashboard has them`);

  if (dryRun) {
    console.log(`dry run: would deploy to ${projectName} on branch main`);
  } else {
    const deploy = spawnSync(
      wrangler,
      ["pages", "deploy", "public", "--project-name", projectName, "--branch", "main", "--commit-dirty=true"],
      { cwd: stagingDir, stdio: "inherit" },
    );
    process.exitCode = deploy.status ?? 1;
  }
} finally {
  await rm(stagingDir, { recursive: true, force: true });
}
