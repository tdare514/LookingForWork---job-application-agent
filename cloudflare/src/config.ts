export const LIMITS = {
  maxRows: 50,
  maxBodyBytes: 16_384,
  rateLimitRequests: 30,
  rateLimitWindowSeconds: 60,
} as const;

export const API_PREFIX = "/api/";

export function clampLimit(value: string | null): number {
  const parsed = Number.parseInt(value ?? "", 10);
  if (!Number.isFinite(parsed) || parsed < 1) return LIMITS.maxRows;
  return Math.min(parsed, LIMITS.maxRows);
}
