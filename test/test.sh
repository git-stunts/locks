#!/usr/bin/env bash
# Tests for git-locks. Pure bash, no framework: each case makes its own
# temporary repository, drives bin/git-locks, and asserts exit codes, stdout,
# stderr, and the refs left behind. RED before the binary exists: every case
# fails on "command not found".
#
# Oracle: exit status, exact refs under refs/locks/, and substrings of the
# messages that name a holder. Every input is constructed here; the clock is
# fixed with GIT_LOCKS_NOW. Blind spot: the concurrency case proves exactly one
# winner among N racers on one machine; it does not model a networked remote.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HERE}/../bin:${PATH}"
PASS=0
FAIL=0
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

mkrepo() {
  local d
  d="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-test.XXXXXX")"
  git -C "${d}" init -q -b main
  printf '%s' "${d}"
}

refs() { git -C "$1" for-each-ref --format='%(refname)' "refs/locks/${2:-}" | sort; }

export GIT_LOCKS_NOW=1000000

# ---------------------------------------------------------------- claim / check / list

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks claim --job j1 --holder luma-63 notes/x.md 'briefs/2026-09-15/y z.md' 2>&1)"
rc=$?
check "claim exits 0" "${rc}" "0"
contains "claim prints the holder" "${out}" "holder: luma-63"
got="$(refs "${R}" | wc -l | tr -d ' ')"
check "claim writes one job ref and one ref per path" "${got}" "3"
got="$(refs "${R}" jobs/)"
check "the job ref exists" "${got}" "refs/locks/jobs/j1"

out="$(git-locks check notes/x.md 2>&1)"
rc=$?
check "check on a held path exits 1" "${rc}" "1"
contains "check names the holder" "${out}" "luma-63"
contains "check names the job" "${out}" "j1"

out="$(git-locks check notes/free.md 2>&1)"
rc=$?
check "check on a free path exits 0" "${rc}" "0"
contains "check says free" "${out}" "free"

out="$(git-locks check 'briefs/2026-09-15/y z.md' 2>&1)"
check "a path with a space is held" "$?" "1"

out="$(git-locks check ./notes/x.md 2>&1)"
check "a leading ./ names the same path" "$?" "1"

out="$(git-locks list 2>&1)"
contains "list shows the holder" "${out}" "luma-63"
contains "list shows the job" "${out}" "j1"
contains "list shows the path with the space" "${out}" "briefs/2026-09-15/y z.md"

# ---------------------------------------------------------------- conflict / disjoint / re-claim

out="$(git-locks claim --job j2 --holder luma-aa notes/x.md 2>&1)"
rc=$?
check "overlapping claim by another job exits 1" "${rc}" "1"
contains "overlapping claim names the holder" "${out}" "luma-63"
contains "overlapping claim names the path" "${out}" "notes/x.md"
got="$(refs "${R}" jobs/j2)"
check "a refused claim leaves no job ref behind" "${got}" ""

out="$(git-locks claim --job j2 --holder luma-aa notes/other.md 2>&1)"
check "a disjoint claim by another job exits 0" "$?" "0"
got="$(refs "${R}" | wc -l | tr -d ' ')"
check "two jobs, three paths" "${got}" "5"

out="$(git-locks claim --job j1 --holder luma-63 notes/x.md notes/added.md 2>&1)"
check "re-claim by the same job exits 0" "$?" "0"
git-locks check 'briefs/2026-09-15/y z.md' >/dev/null 2>&1
check "re-claim frees the path no longer listed" "$?" "0"
git-locks check notes/added.md >/dev/null 2>&1
check "re-claim holds the path newly listed" "$?" "1"

out="$(git-locks claim --job j2 --holder luma-aa notes/added.md 2>&1)"
check "the re-claimed path is held against another job" "$?" "1"

# ---------------------------------------------------------------- release

out="$(git-locks release --job j1 2>&1)"
check "release exits 0" "$?" "0"
got="$(refs "${R}")"
h="$(printf '%s' notes/other.md | git hash-object --stdin)"
check "release removes the job ref and its path refs" "${got}" "refs/locks/jobs/j2
refs/locks/paths/${h}"
out="$(git-locks release --job j1 2>&1)"
check "release of a missing lock exits 0" "$?" "0"
contains "release of a missing lock says so" "${out}" "no lock"

# ---------------------------------------------------------------- expiry

R="$(mkrepo)"
cd "${R}" || exit 2
GIT_LOCKS_NOW=1000 git-locks claim --job old --holder luma-aa --ttl 100 notes/e.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=1050 git-locks check notes/e.md 2>&1)"
check "before expiry the path is held" "$?" "1"
out="$(GIT_LOCKS_NOW=1200 git-locks check notes/e.md 2>&1)"
rc=$?
check "after expiry the path is free" "${rc}" "0"
contains "after expiry check still names the expired holder" "${out}" "expired"
contains "after expiry check names who held it" "${out}" "luma-aa"
out="$(GIT_LOCKS_NOW=1200 git-locks list 2>&1)"
contains "list marks the lock expired" "${out}" "expired"
out="$(GIT_LOCKS_NOW=1200 git-locks claim --job new --holder luma-63 notes/e.md 2>&1)"
check "a claim over an expired lock succeeds" "$?" "0"
got="$(refs "${R}" jobs/)"
check "the expired job ref is evicted by the claim" "${got}" "refs/locks/jobs/new"
out="$(GIT_LOCKS_NOW=1050 git-locks claim --job other --holder luma-aa notes/e.md 2>&1)"
check "the new lock is held again" "$?" "1"

GIT_LOCKS_NOW=1000 git-locks claim --job sweepme --holder luma-aa --ttl 10 notes/s.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=5000 git-locks sweep 2>&1)"
check "sweep exits 0" "$?" "0"
contains "sweep names what it removed" "${out}" "sweepme"
got="$(refs "${R}" jobs/)"
check "sweep removes only expired locks" "${got}" "refs/locks/jobs/new"

# ---------------------------------------------------------------- usage refusals

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job u --holder h >/dev/null 2>&1
check "claim with no path exits 2" "$?" "2"
git-locks claim --holder h a.md >/dev/null 2>&1
check "claim with no --job exits 2" "$?" "2"
git-locks claim --job u a.md >/dev/null 2>&1
check "claim with no --holder exits 2" "$?" "2"
git-locks claim --job u --holder h /abs/path.md >/dev/null 2>&1
check "an absolute path is refused with 2" "$?" "2"
git-locks claim --job u --holder h ../escape.md >/dev/null 2>&1
check "a .. path is refused with 2" "$?" "2"
git-locks claim --job 'bad name' --holder h a.md >/dev/null 2>&1
check "a job id with a space is refused with 2" "$?" "2"
git-locks bogus >/dev/null 2>&1
check "an unknown subcommand exits 2" "$?" "2"
got="$(refs "${R}")"
check "usage refusals leave no refs" "${got}" ""
cd /
git-locks list >/dev/null 2>&1
check "outside a repository exits 2" "$?" "2"

# ---------------------------------------------------------------- one winner under contention

R="$(mkrepo)"
cd "${R}" || exit 2
wins=0
pids=()
for i in $(seq 1 20); do
  (git-locks claim --job "racer${i}" --holder "h${i}" contended.md >/dev/null 2>&1) &
  pids+=($!)
done
for p in "${pids[@]}"; do
  if wait "${p}"; then wins=$((wins + 1)); fi
done
check "twenty concurrent claims on one path: exactly one wins" "${wins}" "1"
got="$(refs "${R}" jobs/ | wc -l | tr -d ' ')"
check "exactly one job ref survives the race" "${got}" "1"
got="$(refs "${R}" paths/ | wc -l | tr -d ' ')"
check "exactly one path ref survives the race" "${got}" "1"

# ---------------------------------------------------------------- multi-path claims are all-or-nothing

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job a --holder ha shared.md >/dev/null 2>&1
git-locks claim --job b --holder hb mine.md shared.md >/dev/null 2>&1
check "a claim with one held path among several is refused" "$?" "1"
git-locks check mine.md >/dev/null 2>&1
check "and the free path in that claim was not taken" "$?" "0"

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
if ((FAIL > 0)); then
  printf 'failed: %s\n' "${FAILED[@]}"
  exit 1
fi
