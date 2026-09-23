export const LIMITS = {
  maxRows: 50,
  maxBodyBytes: 16_384,
  rateLimitRequests: 30,
  rateLimitWindowSeconds: 60,
  maxTrackedClients: 1_000,
  dailyRequestQuota: 1_000,
} as const;

export type AccountConfig = {
  accountPlan: "free";
  dailyRequestQuota: number;
};

export function readAccountConfig(env: Record<string, string | undefined>): AccountConfig | null {
  if (env.FREE_TIER_ENABLED !== "true" || env.ACCOUNT_PLAN !== "free") return null;
  const quota = Number.parseInt(env.DAILY_REQUEST_QUOTA ?? "", 10);
  if (!Number.isInteger(quota) || quota < 1 || quota > LIMITS.dailyRequestQuota) return null;
  return { accountPlan: "free", dailyRequestQuota: quota };
}

export function clampLimit(value: string | null): number {
  const parsed = Number.parseInt(value ?? "", 10);
  if (!Number.isFinite(parsed) || parsed < 1) return LIMITS.maxRows;
  return Math.min(parsed, LIMITS.maxRows);
}

const BODY_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// A body without a declared length would be read unbounded by request.json(),
// so a state-changing request must say how big it is before anything reads it.
export function bodyTooLarge(method: string, contentLength: string | null): boolean {
  if (!BODY_METHODS.has(method)) return false;
  if (contentLength === null || !/^\d+$/.test(contentLength)) return true;
  return Number.parseInt(contentLength, 10) > LIMITS.maxBodyBytes;
}
