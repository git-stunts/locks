#!/usr/bin/env bash
# shellcheck source=scripts/require-docker.sh
source "${BASH_SOURCE[0]%/*}/../scripts/require-docker.sh" || exit 1
# Prove that skipping the live Unicode integration cannot hide a failure in the
# deterministic locale-selection checks that run before it.
set -uo pipefail
unset GIT_LOCKS_TEST_LOCALES # every case below picks its own inventory

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

out="$(GIT_LOCKS_TEST_REQUIRE_UTF8=0 GIT_LOCKS_TEST_LOCALES=$'C\nPOSIX' GIT_LOCKS_TEST_CALIBRATE_FAILURE=1 bash "${HERE}/unicode-locale.sh" 2>&1)"
rc=$?
check "a skipped integration preserves an earlier fixture failure" "${rc}" "1"
case "${out}" in
  *'1 failed, 1 skipped'*) got=yes ;;
  *) got=no ;;
esac
check "the calibration reports both the failure and the skip" "${got}" "yes"

# CI sets GIT_LOCKS_TEST_REQUIRE_UTF8=1 so a broken locale lookup cannot pass as a skip.
out="$(GIT_LOCKS_TEST_LOCALES=$'C\nPOSIX' GIT_LOCKS_TEST_REQUIRE_UTF8=1 bash "${HERE}/unicode-locale.sh" 2>&1)"
rc=$?
check "a required Unicode integration fails when no UTF-8 locale exists" "${rc}" "1"
case "${out}" in
  *'FAIL Unicode integration requires a UTF-8 locale'*) got=yes ;;
  *) got=no ;;
esac
check "and names the missing UTF-8 locale as the failure" "${got}" "yes"

# musl images (the bash:5.2 image behind make test-docker) ship no locale command;
# the integration must still find a UTF-8 locale by probing for one.
SHIM="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-locale-shim.XXXXXX")"
printf '#!/bin/sh\nexit 127\n' >"${SHIM}/locale"
chmod +x "${SHIM}/locale"
out="$(PATH="${SHIM}:${PATH}" GIT_LOCKS_TEST_REQUIRE_UTF8=1 bash "${HERE}/unicode-locale.sh" 2>&1)"
rc=$?
rm -rf -- "${SHIM}"
check "without a locale command the integration still runs and passes" "${rc}" "0"
case "${out}" in
  *'info Unicode integration locale: '*'0 failed, 0 skipped'*) got=yes ;;
  *) got=no ;;
esac
check "and reports the probed locale with nothing skipped" "${got}" "yes"

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
((FAIL == 0))
