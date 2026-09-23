// The local board's states (jobagent.tracking.board.State), in the same order.
// tests/test_cloudflare_contract.py fails if the two drift.
export const APPLICATION_STATUSES = [
  "new",
  "ready",
  "applied",
  "waiting",
  "interview",
  "offer",
  "rejected",
  "skipped",
] as const;

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

export type TrackerApplication = {
  id: string;
  company: string;
  title: string;
  location: string;
  url: string;
  deadline: string | null;
  status: ApplicationStatus;
  nextAction: string | null;
  nextActionDate: string | null;
  updatedAt: string;
  version: number;
};

export type TrackerResponse = {
  applications: TrackerApplication[];
  limit: number;
  source: "synthetic" | "d1";
};

export function isApplicationStatus(value: string): value is ApplicationStatus {
  return APPLICATION_STATUSES.includes(value as ApplicationStatus);
}

// Everything the hosted tracker will accept. Anything else in a payload is a
// refusal, not a silent drop. notes and state_reason are deliberately absent:
// see ADR 0010 and tests/test_cloudflare_contract.py.
export const SYNC_FIELDS = [
  "id",
  "company",
  "title",
  "location",
  "url",
  "deadline",
  "status",
  "nextAction",
  "nextActionDate",
  "version",
] as const;

export type SyncApplication = Omit<TrackerApplication, "updatedAt">;
