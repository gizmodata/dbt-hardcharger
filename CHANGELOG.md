# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

The first version, 0.1.0: the Hardcharger™ port of
[dbt-gizmosql](https://github.com/gizmodata/dbt-gizmosql) 1.12.7.

### Added

- The `hardcharger` dbt adapter (`type: hardcharger`) on
  [adbc-driver-hardcharger](https://github.com/gizmodata/hardcharger-adbc): `hardcharger://`
  URIs, port 31337, TLS on by default (`tls: false` for plain HTTP; it never falls back by
  itself).
- Everything dbt-gizmosql 1.12.7 does: table, view, incremental (`append`, `delete+insert`,
  `merge`, `microbatch`) and ephemeral models, snapshots, the server-side `external`
  materialization (Parquet, CSV, JSON, partitioned, object storage), Python models (local
  DuckDB, record batch streams, yielded ADBC readers, `session.remote_sql()` pushdown), seeds
  read by DuckDB's CSV reader and bulk-ingested, DuckLake catalogs, enforced constraints,
  `persist_docs`, `dbt docs generate`, `dbt show` on Python models, unit tests and the DuckDB
  utility macros.
- Sign-in: `auth_type` `password`, `token` (a Hardcharger access token), `client_certificate`
  (mutual TLS: `tls_client_cert` and `tls_client_key`, no password) and `external` (the server's
  browser sign-in on the server's own port, with `oauth_browser`). A browser sign-in happens
  once per dbt process: every connection of the run shares it (dbt opens five for a one-model
  run, which would otherwise be five sign-ins).
- TLS settings: `tls_root_certs`, `tls_skip_verify`, and the client certificate's
  `tls_client_cert` / `tls_client_key`, each a path or PEM text.
- Profile checks before anything is sent: an unknown `auth_type`, a password with a token or a
  certificate sign-in, a certificate without its key, TLS files with `tls: false`, browser
  settings without `auth_type: external`, each with a message naming the setting.
- A connection to a server that isn't Hardcharger (ADBC vendor name) is refused.

### Changed (from dbt-gizmosql)

- Profile names: `tls` replaces `use_encryption`/`use_tls`, and dbt-gizmosql's
  `disable_certificate_verification` alias is gone (`tls_skip_verify`).
- dbt's `grants` config warns that it isn't applied yet (dbt-gizmosql said GizmoSQL doesn't
  support grants; Hardcharger has `GRANT`, the adapter doesn't apply it yet).

### Tests and CI

- dbt's adapter test suite (dbt-tests-adapter 1.20) and dbt-gizmosql's own tests, against real
  `hardcharger-server` processes from `ghcr.io/gizmodata/hardcharger:main`, over TLS with a
  certificate the tests verify: the same 184 tests pass as in dbt-gizmosql, with the same 3
  skipped (they still fail on Hardcharger for the same reasons: DuckDB's parser, and the
  client-side CSV reader's integer width).
- Sign-in tests against real servers: password over TLS and plain HTTP, a token, a client
  certificate and the browser sign-in (with a mock identity provider), each with a refusal twin
  that checks the reason (an untrusted certificate, TLS against a plain-HTTP server, a wrong
  password, a bad token, an unknown certificate identity, a rejected browser sign-in).
- The README's examples run as written (`tests/functional/test_readme.py`), and CI installs with
  the README's Installation commands.
- The S3 test uses a Versity S3 gateway the workflow starts, and checks the object through the
  S3 API (boto3) instead of the gateway's disk.
- The tests read only `DBT_HARDCHARGER_TEST_*` variables, dial `127.0.0.1`, and fail, never
  skip, without a server or S3 gateway.
- CI: the README install, ruff (lint and format), mypy, Python 3.11 to 3.14, and a
  lowest-dependencies job; `release.yml` runs all of it on the tagged commit before building and
  creating a GitHub Release (no PyPI yet).
- The driver is built from the hardcharger-adbc commit pinned in `.github/hardcharger-adbc.ref`
  (`13f4eb4`: Warp SQL protocol 1.0.0, on warp-sql-adbc `a81c326`, tested against
  `hardcharger-server` 2.0.0-rc.1); moving the pin is its own change, merged with a green CI run.
  With it, browser sign-in runs on the server's own port (Warp SQL spec §4.3): the profile's
  `oauth_url` and `oauth_port` are gone (an `oauth_browser` without `auth_type: external` is
  still refused), and a plain-HTTP server reached with TLS is refused with the driver's own
  message ("speaks plain HTTP, not TLS").
- `scripts/test-in-docker.sh` runs the suite in a Linux container on a laptop, with the server
  from the `:main` image and the driver built at the pinned commit.

### Documentation

- The README banner is the new Hardcharger™ logo, the bull mascot lockup in a light and a dark
  version that follows the reader's color scheme, in place of the GizmoData banner card.
