# Changelog

All notable changes follow Keep a Changelog and this project uses semantic versioning.

## Unreleased

### Added

- Transactional SQLite storage with schema migrations, WAL, compare-and-set, and a
  legacy JSON importer.
- Secure local owner authentication, SMTP email, portable Compose deployment, and
  lightweight/browser/full images.
- Optional GCP and Gmail dependency groups and a sanitized GCP quick-start staging
  repository.

### Changed

- SQLite and local authentication are the portable defaults.
- Runtime state is mounted at `/data` in containers.
- GCP infrastructure consumes an immutable released full image and is no longer owned
  by the core repository.

### Migration

- Existing JSON-backed local users should back up `.state`, run
  `switchgear import-storage-json`, and mount the resulting database and artifacts at
  `/data`.
- Existing GCP users must preserve their backend bucket and resource addresses when
  moving Terraform source; import or use `moved` blocks rather than recreating stateful
  resources.
