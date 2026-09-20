import type { PagesFunction } from "@cloudflare/workers-types";

export const onRequestGet: PagesFunction = () =>
  Response.json({ ok: true, service: "jobagent-companion", mode: "synthetic-local" });
