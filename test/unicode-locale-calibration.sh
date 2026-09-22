#!/usr/bin/env bash
# Prove that skipping the live Unicode integration cannot hide a failure in the
# deterministic locale-selection checks that run before it.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0
FAIL=0

check() { # label got want
  if [[ "$2" == "$3" ]]; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$1"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n       got:  %q\n       want: %q\n' "$1" "$2" "$3"
  fi
}

out="$(GIT_LOCKS_TEST_LOCALES=$'C\nPOSIX' GIT_LOCKS_TEST_CALIBRATE_FAILURE=1 bash "${HERE}/unicode-locale.sh" 2>&1)"
rc=$?
check "a skipped integration preserves an earlier fixture failure" "${rc}" "1"
case "${out}" in
  *'1 failed, 1 skipped'*) got=yes ;;
  *) got=no ;;
esac
check "the calibration reports both the failure and the skip" "${got}" "yes"

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
((FAIL == 0))
