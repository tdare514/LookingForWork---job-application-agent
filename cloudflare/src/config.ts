export const SESSION_SECONDS = 30 * 86_400; // 30 days

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

export type AuthConfig = {
  githubClientId: string;
  githubCallbackUrl: string;
  ownerGithubId: string;
  sessionSecret: string;
};

export function readAuthConfig(env: Record<string, string | undefined>): AuthConfig | null {
  const { GITHUB_CLIENT_ID, GITHUB_CALLBACK_URL, OWNER_GITHUB_ID, SESSION_SECRET } = env;
  if (
    !GITHUB_CLIENT_ID ||
    !GITHUB_CALLBACK_URL ||
    !/^\d+$/.test(OWNER_GITHUB_ID ?? "") ||
    !SESSION_SECRET ||
    SESSION_SECRET.length < 32
  ) {
    return null;
  }
  return {
    githubClientId: GITHUB_CLIENT_ID,
    githubCallbackUrl: GITHUB_CALLBACK_URL,
    ownerGithubId: OWNER_GITHUB_ID as string,
    sessionSecret: SESSION_SECRET,
  };
}

// The laptop's credential for /api/sync and /api/purge. A browser session is
// the wrong shape for a CLI, so the machine routes take this bearer token
// instead, and nothing else does.
export function readSyncToken(env: Record<string, string | undefined>): string | null {
  const token = env.SYNC_TOKEN;
  return token && token.length >= 32 ? token : null;
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
