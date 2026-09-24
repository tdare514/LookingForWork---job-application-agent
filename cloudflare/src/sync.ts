import { LIMITS } from "./config.js";
import { isApplicationStatus, SYNC_FIELDS, type SyncApplication } from "./types.js";

const MAX_TEXT = 500;
const MAX_URL = 2_000;

function optionalText(value: unknown, max = MAX_TEXT): string | null {
  if (value === null || value === undefined) return null;
  return typeof value === "string" && value.length <= max ? value : null;
}

// A board row with no posting URL still syncs; the page shows no link for it.
export function parseSyncBody(value: unknown): { applications: SyncApplication[] } | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const body = value as { applications?: unknown };
  if (!Array.isArray(body.applications) || body.applications.length > LIMITS.maxRows) return null;
  const applications: SyncApplication[] = [];
  for (const item of body.applications) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const record = item as Record<string, unknown>;
    if (Object.keys(record).some((key) => !SYNC_FIELDS.includes(key as (typeof SYNC_FIELDS)[number]))) return null;
    if (
      typeof record.id !== "string" || record.id.length === 0 || record.id.length > 100 ||
      typeof record.company !== "string" || record.company.length === 0 || record.company.length > MAX_TEXT ||
      typeof record.title !== "string" || record.title.length === 0 || record.title.length > MAX_TEXT ||
      typeof record.location !== "string" || record.location.length > MAX_TEXT ||
      typeof record.url !== "string" || record.url.length > MAX_URL ||
      (record.url !== "" && !/^https?:\/\//i.test(record.url)) ||
      typeof record.status !== "string" || !isApplicationStatus(record.status) ||
      !Number.isInteger(record.version) || typeof record.version !== "number" || record.version < 0
    ) return null;
    const deadline = optionalText(record.deadline, 10);
    const nextAction = optionalText(record.nextAction);
    const nextActionDate = optionalText(record.nextActionDate, 10);
    if (record.deadline !== null && record.deadline !== undefined && deadline === null) return null;
    if (record.nextAction !== null && record.nextAction !== undefined && nextAction === null) return null;
    if (record.nextActionDate !== null && record.nextActionDate !== undefined && nextActionDate === null) return null;
    applications.push({
      id: record.id,
      company: record.company,
      title: record.title,
      location: record.location,
      url: record.url,
      deadline,
      status: record.status,
      nextAction,
      nextActionDate,
      version: record.version,
    });
  }
  return { applications };
}

// Ids the laptop no longer has on the board. The laptop is the source of truth
// for which rows exist, so these are removed without a version check.
export function parseRemovals(value: unknown): string[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > LIMITS.maxRows) return null;
  if (!value.every((id) => typeof id === "string" && id.length > 0 && id.length <= 100)) return null;
  return value as string[];
}
