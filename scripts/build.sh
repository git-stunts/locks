#!/usr/bin/env bash
# Assemble bin/git-locks from lib/*.sh in lexical order, generating the schema module from
# schema/git-locks.schema.json (minified to one line) between the modules numbered below 95
# and 99-main.sh. `make build` writes bin/git-locks; `scripts/build.sh <path>` writes elsewhere,
# which is how the test suite checks that the committed script is exactly what lib/ builds.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="${1:-${here}/bin/git-locks}"
schema="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])), separators=(",", ":"), ensure_ascii=False))' "${here}/schema/git-locks.schema.json")"
tmp="$(mktemp "${TMPDIR:-/tmp}/git-locks-build.XXXXXX")"
{
  for f in "${here}"/lib/[0-8][0-9][0-9]-*.sh "${here}"/lib/9[0-8][0-9]-*.sh; do
    [[ -e "${f}" ]] && cat "${f}"
  done
  printf 'cmd_schema() { # the public output schema, one JSON line; the pretty form is schema/git-locks.schema.json in the repository\n'
  printf '  (($# == 0)) || usage\n'
  printf "  cat <<'EOF'\n%s\nEOF\n}\n\n" "${schema}"
  cat "${here}/lib/990-main.sh"
} >"${tmp}"
chmod 0755 "${tmp}"
mv "${tmp}" "${out}"
