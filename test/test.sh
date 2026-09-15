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
n=0 # line counts, set by lines()

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

lines() { # VAR TEXT: set VAR to the number of lines in TEXT
  local count
  count="$(printf '%s\n' "$2" | wc -l)"
  printf -v "$1" '%s' "${count//[[:space:]]/}"
}

SCHEMA_FILE="${HERE}/../schema/git-locks.schema.json"
valid() { # label TEXT: every non-empty line of TEXT validates against the public schema (python3 + jsonschema)
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

refs() { # subject-repo [prefix] -> refs in whatever store resolves for it
  local store
  store="$(cd "$1" && git-locks --text store)" || return 1
  git --git-dir="${store}" for-each-ref --format='%(refname)' "refs/locks/${2:-}" | sort
}

export GIT_LOCKS_NOW=1000000
HOME="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-home.XXXXXX")"
export HOME
unset GIT_LOCKS_STORE GIT_LOCKS_HOME

# ---------------------------------------------------------------- claim / check / list

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks claim --job j1 --holder luma-63 notes/x.md 'briefs/2026-09-15/y z.md' 2>&1)"
rc=$?
check "claim exits 0" "${rc}" "0"
contains "claim prints the holder" "${out}" '"holder":"luma-63"'
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
contains "check says free" "${out}" '"state":"free"'

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
h="$(printf '%s' notes/other.md | git hash-object --stdin)" # content hash: identical in any store
check "release removes the job ref and its path refs" "${got}" "refs/locks/jobs/j2
refs/locks/paths/${h}"
out="$(git-locks release --job j1 2>&1)"
check "release of a missing lock exits 0" "$?" "0"
contains "release of a missing lock says so" "${out}" '"event":"nothing"'

# ---------------------------------------------------------------- expiry

R="$(mkrepo)"
cd "${R}" || exit 2
GIT_LOCKS_NOW=1000 git-locks claim --job old --holder luma-aa --ttl 100 notes/e.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=1050 git-locks check notes/e.md 2>&1)"
check "before expiry the path is held" "$?" "1"
out="$(GIT_LOCKS_NOW=1200 git-locks check notes/e.md 2>&1)"
rc=$?
check "after expiry the path is free" "${rc}" "0"
contains "after expiry check still names the expired holder" "${out}" '"state":"expired"'
contains "after expiry check names who held it" "${out}" "luma-aa"
out="$(GIT_LOCKS_NOW=1200 git-locks list 2>&1)"
contains "list marks the lock expired" "${out}" '"state":"expired"'
out="$(GIT_LOCKS_NOW=1200 git-locks claim --job new --holder luma-63 notes/e.md 2>&1)"
check "a claim over an expired lock succeeds" "$?" "0"
got="$(refs "${R}" jobs/)"
check "the expired job ref is evicted by the claim" "${got}" "refs/locks/jobs/new"
out="$(GIT_LOCKS_NOW=1050 git-locks claim --job other --holder luma-aa notes/e.md 2>&1)"
check "the new lock is held again" "$?" "1"

GIT_LOCKS_NOW=1000 git-locks claim --job sweepme --holder luma-aa --ttl 10 notes/s.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=5000 git-locks sweep 2>&1)"
check "sweep exits 0" "$?" "0"
contains "sweep names what it removed" "${out}" '"event":"swept","job":"sweepme"'
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

# ---------------------------------------------------------------- where the store lives

R="$(mkrepo)"
cd "${R}" || exit 2
top="$(git rev-parse --show-toplevel)"
got="$(git-locks --text store)"
check "the default store is under HOME/.git-stunts/locks mirroring the subject's absolute path" "${got}" "${HOME}/.git-stunts/locks${top}"
git-locks claim --job d --holder h a.md >/dev/null 2>&1
got="$(git -C "${R}" for-each-ref refs/locks/)"
check "by default the subject repo gets no refs at all" "${got}" ""
bare="$(git --git-dir="${HOME}/.git-stunts/locks${top}" rev-parse --is-bare-repository)"
check "the default store is a bare repository" "${bare}" "true"
R2="$(mkrepo)"
cd "${R2}" || exit 2
git-locks check a.md >/dev/null 2>&1
check "a second subject repo has its own store, so the same path is free there" "$?" "0"

cd "${R}" || exit 2
git worktree add -q "${R}-wt" -b wt >/dev/null 2>&1
cd "${R}-wt" || exit 2
git-locks check a.md >/dev/null 2>&1
check "a linked worktree shares its main repo's store" "$?" "1"

cd "${R}" || exit 2
common="$(git rev-parse --path-format=absolute --git-common-dir)"
got="$(GIT_LOCKS_STORE=self git-locks --text store)"
check "GIT_LOCKS_STORE=self resolves to the subject's own git dir" "${got}" "${common}"
GIT_LOCKS_STORE=self git-locks claim --job s --holder h self.md >/dev/null 2>&1
got="$(git -C "${R}" for-each-ref --format='%(refname)' refs/locks/jobs/)"
check "self mode writes refs into the subject repo" "${got}" "refs/locks/jobs/s"
GIT_LOCKS_STORE=self git-locks check a.md >/dev/null 2>&1
check "self mode does not see the default store's locks" "$?" "0"

custom="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-store.XXXXXX")/store"
git config locks.store "${custom}"
got="$(git-locks --text store)"
check "git config locks.store picks a custom store path" "${got}" "${custom}"
git-locks claim --job c --holder h custom.md >/dev/null 2>&1
bare="$(git --git-dir="${custom}" rev-parse --is-bare-repository)"
check "the custom store is created bare on first use" "${bare}" "true"
got="$(GIT_LOCKS_STORE=self git-locks --text store)"
check "the environment overrides the config" "${got}" "${common}"
git config --unset locks.store
got="$(GIT_LOCKS_HOME=/tmp/elsewhere git-locks --text store)"
check "GIT_LOCKS_HOME relocates the default store root" "${got}" "/tmp/elsewhere/locks${top}"
git-locks store extra >/dev/null 2>&1
check "store takes no arguments" "$?" "2"

# ---------------------------------------------------------------- the CLI surface: JSONL by default, --text for humans

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks --help 2>&1)"
check "--help exits 0" "$?" "0"
contains "--help prints the usage" "${out}" "git locks [--text] claim"
out="$(git-locks help 2>&1)"
check "help exits 0" "$?" "0"
git-locks >/dev/null 2>&1
check "no arguments is still a usage error, exit 2" "$?" "2"
out="$(git-locks version 2>&1)"
check "version exits 0" "$?" "0"
contains "version is JSON by default" "${out}" '{"name":"git-locks","version":"'
out="$(git-locks --text version 2>&1)"
rc=1
[[ "${out}" =~ ^git-locks\ [0-9]+\.[0-9]+\.[0-9]+$ ]] && rc=0
check "--text version is 'git-locks <semver>'" "${rc}" "0"
out="$(git-locks claim --help 2>&1)"
check "claim --help exits 0" "$?" "0"
contains "claim --help shows claim's own usage" "${out}" "--holder"

jsonl_ok() { python3 -c 'import json,sys; [json.loads(l) for l in sys.stdin if l.strip()]'; }

out="$(git-locks claim --job jj --holder hh 'a b.md' c.md 2>&1)"
lines n "${out}"
check "claim is one JSON line" "${n}" "1"
contains "claim line carries the event" "${out}" '"event":"claimed"'
contains "claim line carries the paths as an array" "${out}" '"paths":["a b.md","c.md"]'
jsonl_ok <<<"${out}" >/dev/null 2>&1
check "claim line parses as JSON" "$?" "0"
valid "claim line" "${out}"

out="$(git-locks check 'a b.md' free.md c.md 2>/dev/null)"
check "check still exits 1 when a path is held" "$?" "1"
lines n "${out}"
check "check streams one line per path" "${n}" "3"
contains "check line carries the path with its space" "${out}" '"path":"a b.md","state":"held","holder":"hh","job":"jj","expires":'
contains "check reports the free path as free" "${out}" '{"path":"free.md","state":"free"}'
jsonl_ok <<<"${out}" >/dev/null 2>&1
check "check lines parse as JSON" "$?" "0"
valid "check lines (held and free)" "${out}"
out="$(git-locks --text check 'a b.md' free.md 2>&1)"
contains "--text check is the human line" "${out}" "a b.md: held by hh (job jj, until "

err="$(git-locks claim --job other --holder oo 'a b.md' c.md 2>&1 >/dev/null)"
lines n "${err}"
check "a refused claim streams one refusal line per held path on stderr" "${n}" "2"
contains "refusal line names the holder" "${err}" '"event":"refused","path":"a b.md","holder":"hh","job":"jj"'
jsonl_ok <<<"${err}" >/dev/null 2>&1
check "refusal lines parse as JSON" "$?" "0"
valid "refusal lines" "${err}"
err="$(git-locks --text claim --job other --holder oo 'a b.md' 2>&1 >/dev/null)"
contains "--text refusal is the human line" "${err}" "refused — a b.md: held by hh (job jj"

out="$(git-locks list 2>&1)"
lines n "${out}"
check "list streams one line per lock" "${n}" "1"
contains "list line carries job, holder, state" "${out}" '{"job":"jj","holder":"hh","state":"live","claimed":'
contains "list line carries the paths as an array" "${out}" '"paths":["a b.md","c.md"]'
jsonl_ok <<<"${out}" >/dev/null 2>&1
check "list line parses as JSON" "$?" "0"
valid "list line" "${out}"
out="$(git-locks --text list 2>&1)"
contains "--text list is the table" "${out}" "live    hh  job jj  until "

out="$(git-locks release --job jj 2>&1)"
contains "release is one JSON line" "${out}" '{"event":"released","job":"jj","paths":2}'
valid "release line" "${out}"
out="$(git-locks release --job jj 2>&1)"
valid "release-nothing line" "${out}"
out="$(git-locks list 2>&1)"
check "list with no locks streams nothing" "${out}" ""
out="$(git-locks --text list 2>&1)"
check "--text list with no locks says so" "${out}" "no locks"
out="$(git-locks store 2>&1)"
contains "store is one JSON line" "${out}" '{"store":"'
valid "store line" "${out}"
out="$(git-locks version 2>&1)"
valid "version line" "${out}"
GIT_LOCKS_NOW=1000 git-locks claim --job exp --holder h --ttl 1 gone.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=2000 git-locks check gone.md 2>&1)"
valid "check line for an expired lock" "${out}"
out="$(GIT_LOCKS_NOW=2000 git-locks list 2>&1)"
valid "list line for an expired lock" "${out}"
out="$(GIT_LOCKS_NOW=2000 git-locks sweep 2>&1)"
valid "sweep line" "${out}"

out="$(git-locks schema 2>&1)"
check "schema exits 0" "$?" "0"
got="$(diff <(printf '%s\n' "${out}") "${SCHEMA_FILE}" && printf identical)"
check "schema output is byte-identical to schema/git-locks.schema.json" "${got}" "identical"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "${SCHEMA_FILE}" >/dev/null 2>&1
check "the schema file is valid JSON" "$?" "0"

# Streaming: the first line arrives before the last path is examined.
first="$( (
  git-locks check one.md two.md three.md 2>/dev/null
  true
) | head -n 1)"
contains "the first check line is a complete object on its own" "${first}" '{"path":"one.md","state":"free"}'

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
if ((FAIL > 0)); then
  printf 'failed: %s\n' "${FAILED[@]}"
  exit 1
fi
