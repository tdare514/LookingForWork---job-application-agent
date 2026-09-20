export const APPLICATION_STATUSES = [
  "new",
  "pursue",
  "ready",
  "applied",
  "interview",
  "closed",
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
  notes: string | null;
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

export const SYNC_FIELDS = [
  "id",
  "company",
  "title",
  "location",
  "url",
  "deadline",
  "status",
  "notes",
  "nextAction",
  "nextActionDate",
  "version",
] as const;

export type SyncApplication = Omit<TrackerApplication, "updatedAt">;
