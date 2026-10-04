#!/usr/bin/env bash
# shellcheck source=scripts/require-docker.sh
source "${BASH_SOURCE[0]%/*}/../scripts/require-docker.sh" || exit 1
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
found_c=0
found_en_us=0
installed_locales="$(locale -a)"
while IFS= read -r installed; do
  case "${installed,,}" in
    c.utf8 | c.utf-8) found_c=1 ;;
    en_us.utf8 | en_us.utf-8) found_en_us=1 ;;
    *) ;;
  esac
done <<<"${installed_locales}"
[[ "${found_c}" == 1 && "${found_en_us}" == 0 ]]
probe="$(mktemp -d)"
trap 'rm -rf "${probe}"' EXIT
mkdir -p "${probe}/home" "${probe}/work"
git -C "${probe}/work" init -q -b main
export HOME="${probe}/home" GIT_LOCKS_STORE="${probe}/store.git"
merged="$(cd "${probe}/work" && LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 "${ROOT}/bin/git-locks" claim --job unicode-red --holder 'héloïse' 'café/naïve.md' 2>&1)"
[[ "${merged}" == *setlocale* && "${merged}" == *'"event":"claimed"'* ]]
if python3 -c 'import json, sys; [json.loads(line) for line in sys.stdin if line.strip()]' <<<"${merged}" 2>/dev/null; then
  printf 'expected the merged warning and JSON stream to fail parsing\n' >&2
  exit 1
fi
bash "${ROOT}/test/unicode-locale.sh"
no_locale_output="$(GIT_LOCKS_TEST_REQUIRE_UTF8=0 GIT_LOCKS_TEST_LOCALES=$'C\nPOSIX' bash "${ROOT}/test/unicode-locale.sh")"
[[ "${no_locale_output}" == *'SKIP Unicode claim/list/check integration'* ]]
printf 'Missing-locale regression and explicit skip passed.\n'
