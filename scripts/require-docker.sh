#!/usr/bin/env bash
# Safe to source from suites that do not use errexit: refusal exits the caller.
guard_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v node >/dev/null 2>&1; then
  printf 'Tests require the isolated Docker runner. Run make test.\n' >&2
  exit 1
fi
node "${guard_root}/require-docker.mjs" || exit 1
unset guard_root
