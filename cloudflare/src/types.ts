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
};

export type TrackerResponse = {
  applications: TrackerApplication[];
  limit: number;
  source: "synthetic";
};

export function isApplicationStatus(value: string): value is ApplicationStatus {
  return APPLICATION_STATUSES.includes(value as ApplicationStatus);
}
