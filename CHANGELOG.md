# Changelog

All notable changes to this project are recorded here. The format follows Keep a Changelog; versions follow SemVer.

## [Unreleased]

### Added

- JSON Lines by default on every command, one object per result written as each result is known, refusals as objects on stderr; `--text` for the human form. `git locks help` and `<cmd> --help` exit 0; `git locks version`.
- The public output schema, `schema/git-locks.schema.json` (JSON Schema 2020-12), printed byte-for-byte by `git locks schema`; the test suite validates every emitted line against it.
- The store: locks live in a bare repository at `~/.git-stunts/locks/<absolute path of the main repo>` by default, created on first use, shared by a repo's linked worktrees, so the project's own refs stay clean; `GIT_LOCKS_STORE=<path|self>`, `git config locks.store`, and `GIT_LOCKS_HOME` override it; `git locks store` prints what resolved.
- `git locks claim | release | check | list | sweep`: path locks stored as git refs (`refs/locks/jobs/<job>`, `refs/locks/paths/<hash>`) pointing at a plain-text record blob; a claim is one `git update-ref --stdin` transaction, atomic across its paths and across racing claimants; a refused claim names the holder; expiry with a default four-hour TTL; re-claim by the same job replaces its path set; expired locks are claimable over and swept on demand.
- `test/test.sh`: 113 checks in pure bash, including twenty concurrent claimants producing exactly one winner.
- `make lint` (shellcheck with every optional check, shfmt) and `make test`; git hooks under `scripts/hooks/`; GitHub Actions running both.
