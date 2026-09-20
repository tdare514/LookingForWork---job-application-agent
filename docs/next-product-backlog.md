# Next product backlog

## Hosted companion milestone: tracker sync and owner-only writes

Completed on the hosted companion branch:

- Public Pages shell and synthetic, read-only offline snapshot.
- Free-tier fail-closed configuration, bounded body/row/rate limits, and
  browser security headers.
- GitHub OAuth with PKCE, encrypted transaction state, numeric owner-ID
  authorization, rotated server-side sessions, logout revocation, and CSRF
  protection for state changes.
- D1 job rows with an explicit hosted allowlist and a monotonic `version`.
- Authenticated `PUT /api/jobs/:id` updates guarded by `If-Match`.
- Authenticated `POST /api/sync` for bounded laptop-to-cloud tracker batches.
  It rejects unknown/private fields and returns `409` rather than overwriting
  a newer row.

The hosted contract contains tracker fields only: job identity and posting
metadata, board status, notes, next action, dates, and version. It never
accepts profile, resume, contact, work-authorization, compensation, raw
posting, generated-document, OAuth-token, or job-site submission data.

## Remaining acceptance criteria

### Deployment

- [ ] Human records the hosted-data exception and retention/export/purge
      decision in the applicable ADR and threat-model documents.
- [ ] A dedicated Cloudflare Pages project and D1 database are created with
      the free plan verified; unknown or paid billing state blocks deployment.
- [ ] Development and production bindings are separate; no account IDs,
      OAuth secrets, session secrets, real dossier data, or real jobs enter git.
- [ ] GitHub OAuth uses a dedicated app, exact callback URL, immutable owner
      numeric ID, and deployment secrets; the denial path is tested from a
      second account.
- [ ] Synthetic-only deployment passes migration, quota, backup/restore,
      purge, header, secret-scan, and no-submit checks before real data.

### Sync

- [ ] Add a local export/import command with a manifest, checksum, atomic
      validation, idempotency key, and a documented round trip.
- [ ] Define and test cursor-based bidirectional reconciliation; stale writes
      remain explicit conflicts and are never resolved by cloud-wins.
- [ ] Add owner-only export and purge with verification across D1 tables,
      sessions, logs, caches, backups, and deployment artifacts.
- [ ] Add UI controls for authenticated sign-in, sync, conflict display, and
      tracker-only edits; offline mode remains read-only.
- [ ] Run the end-to-end synthetic OAuth, sync, conflict, purge, and
      free-tier deployment gate with a human review of the final diff.
