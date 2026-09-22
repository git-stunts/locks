#!/usr/bin/env bash
# Independent small-store calibration before the informational large benchmark.
set -euo pipefail
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/locks-churn-calibration.XXXXXX")"
trap 'rm -rf "${TMP}"' EXIT
BENCH="${ROOT}/scripts/benchmark-directory-tokens.sh"
if bash "${BENCH}" fixture "${TMP}/wide.git" wide 3 >"${TMP}/out" 2>"${TMP}/err"; then
  printf 'ok fixture command builds three released directory reservations\n'
else
  printf 'FAIL fixture command must build three released directory reservations\n' >&2
  cat "${TMP}/err" >&2
  exit 1
fi

assert() { # description actual expected
  [[ "$2" == "$3" ]] || {
    printf 'FAIL %s: got %s, expected %s\n' "$1" "$2" "$3" >&2
    exit 1
  }
  printf 'ok %s\n' "$1"
}
count_refs() { git --git-dir="$1" for-each-ref --format='%(refname)' "$2" | wc -l | tr -d ' '; }
signature() { # Acquisition ids vary; every other reachable record byte must agree.
  local ref oid line rows body
  rows="$(git --git-dir="$1" for-each-ref --format='%(refname) %(objectname)')"
  while read -r ref oid; do
    [[ -n "${ref}" ]] || continue
    printf '%s\n' "${ref}"
    body="$(git --git-dir="$1" cat-file blob "${oid}")"
    while IFS= read -r line; do
      case "${line}" in acquisition:*) ;; *) printf '%s\n' "${line}" ;; esac
    done <<<"${body}"
  done <<<"${rows}"
}

for shape in wide deep reuse; do
  case "${shape}" in
    wide)
      count=3
      dirs=3
      records=3
      paths=(d00001/file.md d00002/file.md d00003/file.md)
      ;;
    deep)
      count=20
      dirs=20
      records=2
      paths=(g00001/a/b/c/d/e/f/g/h/i/file.md g00002/a/b/c/d/e/f/g/h/i/file.md)
      ;;
    reuse)
      count=5
      dirs=10
      records=1
      paths=(shared/a/b/c/d/e/f/g/h/i/file00001.md shared/a/b/c/d/e/f/g/h/i/file00002.md shared/a/b/c/d/e/f/g/h/i/file00003.md shared/a/b/c/d/e/f/g/h/i/file00004.md shared/a/b/c/d/e/f/g/h/i/file00005.md)
      ;;
    *) exit 2 ;;
  esac
  synthetic="${TMP}/${shape}.git"
  if [[ "${shape}" != wide ]]; then bash "${BENCH}" fixture "${synthetic}" "${shape}" "${count}"; fi
  actual="${TMP}/${shape}-cli.git"
  i=0
  for path in "${paths[@]}"; do
    i=$((i + 1))
    printf -v job 'j%05d' "${i}"
    GIT_LOCKS_STORE="${actual}" GIT_LOCKS_NOW=1000000 "${ROOT}/bin/git-locks" claim --job "${job}" --holder benchmark "${path}" >/dev/null
    GIT_LOCKS_STORE="${actual}" GIT_LOCKS_NOW=1000000 "${ROOT}/bin/git-locks" release --job "${job}" >/dev/null
  done
  got="$(count_refs "${synthetic}" refs/locks/dirs/)"
  assert "${shape} has independently counted directory tokens" "${got}" "${dirs}"
  got="$(count_refs "${synthetic}" refs/locks/jobs/)"
  assert "${shape} has no job refs" "${got}" 0
  got="$(count_refs "${synthetic}" refs/locks/paths/)"
  assert "${shape} has no path refs" "${got}" 0
  got="$(git --git-dir="${synthetic}" for-each-ref --format='%(objectname)' | sort -u | wc -l | tr -d ' ')"
  assert "${shape} retains the expected distinct records" "${got}" "${records}"
  got="$(signature "${synthetic}")"
  want="$(signature "${actual}")"
  assert "${shape} matches actual CLI claim/release records and refs" "${got}" "${want}"
  bash "${BENCH}" verify "${synthetic}" "${dirs}" 0
  GIT_LOCKS_STORE="${synthetic}" GIT_LOCKS_NOW=1000000 "${ROOT}/bin/git-locks" doctor >/dev/null
  printf 'ok %s synthetic fixture is healthy according to the real doctor\n' "${shape}"
done
bash "${BENCH}" fixture "${TMP}/empty.git" wide 0
bash "${BENCH}" verify "${TMP}/empty.git" 0 0
bash "${BENCH}" fixture "${TMP}/live.git" wide 3 live
bash "${BENCH}" verify "${TMP}/live.git" 3 3
got="$(count_refs "${TMP}/live.git" refs/locks/jobs/)"
assert 'live control has independent job count' "${got}" 3
GIT_LOCKS_STORE="${TMP}/live.git" GIT_LOCKS_NOW=1000000 "${ROOT}/bin/git-locks" doctor >/dev/null
printf 'ok live control passes the real doctor\n'
# Deliberate contamination must make the gate fail, rather than time the wrong state.
oid="$(git --git-dir="${TMP}/wide.git" for-each-ref --format='%(objectname)' | head -1)"
git --git-dir="${TMP}/wide.git" update-ref refs/locks/jobs/contamination "${oid}"
if bash "${BENCH}" verify "${TMP}/wide.git" 3 0; then
  printf 'FAIL verifier accepted a live-ref contamination\n' >&2
  exit 1
fi
printf 'ok verifier rejects a contaminated released fixture\n'
# Fixed input corpus prevents oversized/ambiguous setup from consuming the host.
for bad in -1 1x 10001 999999999999999999999999 1.5; do
  if bash "${BENCH}" fixture "${TMP}/invalid-${bad}" wide "${bad}"; then
    printf 'FAIL accepted count %s\n' "${bad}" >&2
    exit 1
  fi
  [[ ! -e "${TMP}/invalid-${bad}" ]] || {
    printf 'FAIL invalid count created a store\n' >&2
    exit 1
  }
done
if bash "${BENCH}" fixture "${TMP}/deep-invalid.git" deep 11; then
  printf 'FAIL accepted incomplete deep shape\n' >&2
  exit 1
fi
before="$(signature "${TMP}/wide.git")"
if bash "${BENCH}" fixture "${TMP}/wide.git" wide 3; then
  printf 'FAIL overwrote an existing fixture\n' >&2
  exit 1
fi
got="$(signature "${TMP}/wide.git")"
assert 'refusing an existing store preserves it' "${got}" "${before}"
if bash "${BENCH}" verify "${TMP}/missing.git" 0 0 >"${TMP}/out" 2>"${TMP}/err"; then
  printf 'FAIL missing store passed the fixture gate\n' >&2
  exit 1
fi
printf 'ok missing store fails the fixture gate\n'
if bash "${BENCH}" run "${TMP}/quick-results" quick >"${TMP}/out" 2>"${TMP}/err"; then
  rows="$(wc -l <"${TMP}/quick-results/observations.csv" | tr -d ' ')"
  assert 'quick matrix retains all 25 raw observations' "${rows}" 26
else
  printf 'FAIL quick matrix must run calibrated command paths\n' >&2
  cat "${TMP}/err" >&2
  exit 1
fi
# Seeded shape samples use hand-counted oracles, independent of the generator.
shape_cases=('wide:0:0:0' 'wide:1:1:1' 'wide:7:7:7' 'deep:10:10:1' 'deep:30:30:3' 'reuse:0:0:0' 'reuse:1:10:1' 'reuse:9:10:1')
fuzz_state=39
for ((sample = 0; sample < 12; sample++)); do
  fuzz_state=$(((fuzz_state * 1103515245 + 12345) % 2147483648))
  IFS=: read -r shape count dirs records <<<"${shape_cases[$((fuzz_state % ${#shape_cases[@]}))]}"
  store="${TMP}/fuzz-${sample}.git"
  bash "${BENCH}" fixture "${store}" "${shape}" "${count}"
  bash "${BENCH}" verify "${store}" "${dirs}" 0 >/dev/null
  got="$(git --git-dir="${store}" for-each-ref --format='%(objectname)' | sort -u | wc -l | tr -d ' ')"
  assert "seed39 shape sample ${sample} reachable records" "${got}" "${records}"
done
printf 'directory-token calibration passed\n'
