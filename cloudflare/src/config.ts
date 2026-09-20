export const LIMITS = {
  maxRows: 50,
  maxBodyBytes: 16_384,
  rateLimitRequests: 30,
  rateLimitWindowSeconds: 60,
  maxTrackedClients: 1_000,
  dailyRequestQuota: 1_000,
} as const;

export const API_PREFIX = "/api/";

export type AccountConfig = {
  accountPlan: "free";
  dailyRequestQuota: number;
};

export type AuthConfig = {
  githubClientId: string;
  githubCallbackUrl: string;
  ownerGithubId: string;
  sessionSecret: string;
};

export function readAccountConfig(env: Record<string, string | undefined>): AccountConfig | null {
  if (env.FREE_TIER_ENABLED !== "true" || env.ACCOUNT_PLAN !== "free") return null;
  const quota = Number.parseInt(env.DAILY_REQUEST_QUOTA ?? "", 10);
  if (!Number.isInteger(quota) || quota < 1 || quota > LIMITS.dailyRequestQuota) return null;
  return { accountPlan: "free", dailyRequestQuota: quota };
}

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

export function clampLimit(value: string | null): number {
  const parsed = Number.parseInt(value ?? "", 10);
  if (!Number.isFinite(parsed) || parsed < 1) return LIMITS.maxRows;
  return Math.min(parsed, LIMITS.maxRows);
}
