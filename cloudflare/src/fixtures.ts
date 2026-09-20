import type { TrackerApplication } from "./types.js";

export const SYNTHETIC_APPLICATIONS: TrackerApplication[] = [
  {
    id: "synthetic-001",
    company: "Example North",
    title: "Operations Analyst",
    location: "Toronto, ON",
    url: "https://example.invalid/jobs/1",
    deadline: "2026-09-20",
    status: "ready",
    notes: "Synthetic fixture: review the tailored package.",
    nextAction: "Review application package",
    nextActionDate: "2026-09-19",
    updatedAt: "2026-09-19T00:00:00Z",
  },
  {
    id: "synthetic-002",
    company: "Sample Works",
    title: "Data Co-op",
    location: "Montreal, QC",
    url: "https://example.invalid/jobs/2",
    deadline: "2026-10-02",
    status: "pursue",
    notes: "Synthetic fixture: compare requirements with the resume source.",
    nextAction: "Read posting and capture requirements",
    nextActionDate: "2026-09-22",
    updatedAt: "2026-09-18T00:00:00Z",
  },
];
