#!/usr/bin/env bash
# Unicode integration coverage that adapts to the UTF-8 locales installed on
# the current system. JSON stdout and shell diagnostics are checked separately.
set -uo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX GIT_OBJECT_DIRECTORY GIT_NAMESPACE

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HERE}/../bin:${PATH}"
SCHEMA_FILE="${HERE}/../schema/git-locks.schema.json"
PASS=0
FAIL=0
SKIP=0
FAILED=()

check() { # label got want
  if [[ "$2" == "$3" ]]; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$1"
  else
    FAIL=$((FAIL + 1))
    FAILED+=("$1")
    printf '  FAIL %s\n       got:  %q\n       want: %q\n' "$1" "$2" "$3"
  fi
}

contains() { # label haystack needle
  if [[ "$2" == *"$3"* ]]; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$1"
  else
    FAIL=$((FAIL + 1))
    FAILED+=("$1")
    printf '  FAIL %s\n       text: %q\n       lacks: %q\n' "$1" "$2" "$3"
  fi
}

valid() { # label text
  local rc
  python3 -c '
import json, sys
import jsonschema
schema = json.load(open(sys.argv[1]))
for line in sys.argv[2].splitlines():
    if line.strip():
        jsonschema.validate(json.loads(line), schema)
' "${SCHEMA_FILE}" "$2" >/dev/null 2>&1
  rc=$?
  check "$1 validates against schema/git-locks.schema.json" "${rc}" "0"
}

finish() {
  printf '\n%d passed, %d failed, %d skipped\n' "${PASS}" "${FAIL}" "${SKIP}"
  if ((FAIL > 0)); then
    printf 'failed:'
    printf ' %s;' "${FAILED[@]}"
    printf '\n'
    return 1
  fi
  return 0
}

select_utf8_locale() { # VAR [locale-a output]: prefer C, then en_US, then any installed UTF-8 locale
  local output_name="$1" available line normalized en_us='' fallback=''
  if (($# > 1)); then
    available="$2"
  else
    available="$(locale -a 2>/dev/null)" || return 1
  fi
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    normalized="${line,,}"
    case "${normalized}" in
      c.utf-8 | c.utf8)
        printf -v "${output_name}" '%s' "${line}"
        return 0
        ;;
      en_us.utf-8 | en_us.utf8)
        [[ -n "${en_us}" ]] || en_us="${line}"
        ;;
      *.utf-8 | *.utf8)
        [[ -n "${fallback}" ]] || fallback="${line}"
        ;;
      *) ;;
    esac
  done <<<"${available}"
  if [[ -n "${en_us}" ]]; then
    printf -v "${output_name}" '%s' "${en_us}"
    return 0
  fi
  if [[ -n "${fallback}" ]]; then
    printf -v "${output_name}" '%s' "${fallback}"
    return 0
  fi
  return 1
}

# Fixed inventories cover platform spellings, preference order, fallback and
# the no-UTF-8 boundary without depending on the machine running the suite.
selected=''
select_utf8_locale selected $'en_US.UTF-8\nC\nC.utf8\nPOSIX'
expected_c_utf8='C.utf8'
[[ "${GIT_LOCKS_TEST_CALIBRATE_FAILURE:-0}" == 1 ]] && expected_c_utf8='calibration-mismatch'
check "locale selection prefers C.utf8 when Linux provides it" "${selected}" "${expected_c_utf8}"
selected=''
select_utf8_locale selected $'C\nC.UTF-8\nPOSIX'
check "locale selection accepts the C.UTF-8 spelling" "${selected}" "C.UTF-8"
selected=''
select_utf8_locale selected $'C\nen_US.utf8\nPOSIX'
check "locale selection accepts the en_US.utf8 spelling" "${selected}" "en_US.utf8"
selected=''
select_utf8_locale selected $'C\nfr_FR.UTF-8\nPOSIX'
check "locale selection falls back to another installed UTF-8 locale" "${selected}" "fr_FR.UTF-8"
selected=''
if select_utf8_locale selected $'C\nPOSIX'; then rc=0; else rc=$?; fi
check "locale selection reports when no UTF-8 locale exists" "${rc}" "1"

UTF8_LOCALE=''
locale_available=0
if [[ -n "${GIT_LOCKS_TEST_LOCALES+x}" ]]; then
  select_utf8_locale UTF8_LOCALE "${GIT_LOCKS_TEST_LOCALES}" && locale_available=1
else
  select_utf8_locale UTF8_LOCALE && locale_available=1
fi
if ((locale_available == 0)); then
  SKIP=$((SKIP + 1))
  printf '  SKIP Unicode claim/list/check integration: install a UTF-8 locale to run it\n'
  finish
  exit $?
fi

printf '  info Unicode integration locale: %s\n' "${UTF8_LOCALE}"

TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-unicode.XXXXXX")"
cleanup() {
  if [[ -n "${TEST_ROOT:-}" && "${TEST_ROOT}" == "${TMPDIR:-/tmp}"/git-locks-unicode.* ]]; then
    rm -rf -- "${TEST_ROOT}"
  fi
}
trap cleanup EXIT

export HOME="${TEST_ROOT}/home"
export GIT_LOCKS_STORE="${TEST_ROOT}/store.git"
export GIT_LOCKS_NOW=1000000
mkdir -p "${HOME}" "${TEST_ROOT}/work"
git -C "${TEST_ROOT}/work" init -q -b main
cd "${TEST_ROOT}/work" || exit 2
STDOUT_FILE="${TEST_ROOT}/stdout"
STDERR_FILE="${TEST_ROOT}/stderr"

LC_ALL="${UTF8_LOCALE}" LANG="${UTF8_LOCALE}" git-locks claim --job unicode --holder 'héloïse' 'café/naïve.md' >"${STDOUT_FILE}" 2>"${STDERR_FILE}"
rc=$?
out="$(<"${STDOUT_FILE}")"
err="$(<"${STDERR_FILE}")"
check "Unicode claim exits 0" "${rc}" "0"
check "Unicode claim writes no diagnostics" "${err}" ""
contains "Unicode claim keeps the holder" "${out}" '"holder":"héloïse"'
contains "Unicode claim keeps the path" "${out}" '"paths":["café/naïve.md"]'
valid "Unicode claim stdout" "${out}"

LC_ALL="${UTF8_LOCALE}" LANG="${UTF8_LOCALE}" git-locks list >"${STDOUT_FILE}" 2>"${STDERR_FILE}"
rc=$?
out="$(<"${STDOUT_FILE}")"
err="$(<"${STDERR_FILE}")"
check "Unicode list exits 0" "${rc}" "0"
check "Unicode list writes no diagnostics" "${err}" ""
contains "Unicode list keeps the holder" "${out}" '"holder":"héloïse"'
contains "Unicode list keeps the path" "${out}" '"paths":["café/naïve.md"]'
valid "Unicode list stdout" "${out}"

LC_ALL="${UTF8_LOCALE}" LANG="${UTF8_LOCALE}" git-locks check 'café/naïve.md' >"${STDOUT_FILE}" 2>"${STDERR_FILE}"
rc=$?
out="$(<"${STDOUT_FILE}")"
err="$(<"${STDERR_FILE}")"
check "Unicode check sees the path held" "${rc}" "1"
check "Unicode check writes no diagnostics" "${err}" ""
contains "Unicode check keeps the holder" "${out}" '"holder":"héloïse"'
contains "Unicode check keeps the path" "${out}" '"path":"café/naïve.md"'
valid "Unicode check stdout" "${out}"

finish
