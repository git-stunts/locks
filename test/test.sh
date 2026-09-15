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

# ---------------------------------------------------------------- see everything: show, ttl, extend, remaining

R="$(mkrepo)"
cd "${R}" || exit 2
GIT_LOCKS_NOW=1000 git-locks claim --job s1 --holder hs --ttl 500 one.md two.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=1100 git-locks show --job s1 2>&1)"
check "show exits 0 for a live lock" "$?" "0"
contains "show carries the state and remaining seconds" "${out}" '"job":"s1","holder":"hs","state":"live","claimed":1000,"expires":1500,"remaining":400,"paths":["one.md","two.md"]'
valid "show line" "${out}"
out="$(GIT_LOCKS_NOW=1100 git-locks --text show --job s1 2>&1)"
contains "--text show names the job" "${out}" "job:       s1"
contains "--text show names the remaining time" "${out}" "remaining: 400s"
contains "--text show lists the paths" "${out}" "one.md"
out="$(GIT_LOCKS_NOW=2000 git-locks show --job s1 2>&1)"
check "show exits 0 for an expired lock too" "$?" "0"
contains "show reports expired with remaining 0" "${out}" '"state":"expired","claimed":1000,"expires":1500,"remaining":0'
err="$(git-locks show --job nope 2>&1 >/dev/null)"
check "show exits 1 for a missing lock" "$?" "1"
contains "show missing is a JSON line on stderr" "${err}" '{"event":"missing","job":"nope"}'
valid "missing line" "${err}"

out="$(GIT_LOCKS_NOW=1100 git-locks ttl --job s1 2>&1)"
check "ttl exits 0" "$?" "0"
check "ttl is one JSON line with the remaining seconds" "${out}" '{"job":"s1","expires":1500,"remaining":400}'
valid "ttl line" "${out}"
out="$(GIT_LOCKS_NOW=1100 git-locks --text ttl --job s1 2>&1)"
check "--text ttl is just the number" "${out}" "400"
git-locks ttl --job nope >/dev/null 2>&1
check "ttl exits 1 for a missing lock" "$?" "1"

out="$(GIT_LOCKS_NOW=1100 git-locks extend --job s1 --ttl 1000 2>&1)"
check "extend exits 0" "$?" "0"
contains "extend reports the new expiry" "${out}" '{"event":"extended","job":"s1","expires":2100}'
valid "extend line" "${out}"
out="$(GIT_LOCKS_NOW=1100 git-locks ttl --job s1 2>&1)"
contains "extend moved the expiry" "${out}" '"remaining":1000'
GIT_LOCKS_NOW=1100 git-locks check one.md >/dev/null 2>&1
check "extend keeps every path held" "$?" "1"
git-locks extend --job nope --ttl 5 >/dev/null 2>&1
check "extend exits 1 for a missing lock" "$?" "1"

out="$(GIT_LOCKS_NOW=1100 git-locks list 2>&1)"
contains "list lines carry remaining seconds" "${out}" '"remaining":1000'
valid "list line with remaining" "${out}"
out="$(GIT_LOCKS_NOW=1100 git-locks check one.md 2>&1)"
contains "check lines carry remaining seconds" "${out}" '"remaining":1000'
valid "check line with remaining" "${out}"

# ---------------------------------------------------------------- with: claim, run, release

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks with --job w1 --holder hw a.md -- sh -c 'git-locks --text check a.md | head -n 1; echo ran' 2>/dev/null)"
rc=$?
check "with exits with the command's status (0)" "${rc}" "0"
contains "the command ran while the path was held" "${out}" "a.md: held by hw (job w1"
contains "the command's stdout passes through untouched" "${out}" "ran"
git-locks check a.md >/dev/null 2>&1
check "with released the lock afterwards" "$?" "0"
err="$(git-locks with --job w1 --holder hw a.md -- true 2>&1 >/dev/null)"
contains "with reports its own claim on stderr, not stdout" "${err}" '"event":"claimed","job":"w1"'
contains "with reports its release on stderr" "${err}" '"event":"released","job":"w1"'
valid "with lifecycle lines" "${err}"
git-locks with --job w2 --holder hw b.md -- sh -c 'exit 7' >/dev/null 2>&1
check "with propagates a non-zero exit status" "$?" "7"
git-locks check b.md >/dev/null 2>&1
check "with releases even when the command fails" "$?" "0"
git-locks claim --job holder --holder other c.md >/dev/null 2>&1
err="$(git-locks with --job w3 --holder hw c.md -- echo never 2>&1 >/dev/null)"
check "with exits 1 when the path is held and no --wait is given" "$?" "1"
contains "with refusal names the holder" "${err}" '"event":"refused","path":"c.md","holder":"other","job":"holder"'
out="$(git-locks with --job w3 --holder hw c.md -- echo never 2>/dev/null)"
check "the command never ran" "${out}" ""
# --wait: the holder releases after one second; with polls and then runs.
(
  sleep 1
  git-locks release --job holder >/dev/null 2>&1
) &
out="$(git-locks with --job w4 --holder hw --wait 10 c.md -- echo finally 2>/dev/null)"
check "with --wait acquires once the holder releases and runs the command" "${out}" "finally"
wait
git-locks claim --job holder2 --holder other d.md >/dev/null 2>&1
git-locks with --job w5 --holder hw --wait 1 d.md -- echo never >/dev/null 2>&1
check "with --wait gives up with exit 1 after the wait" "$?" "1"
git-locks with --job w6 --holder hw e.md >/dev/null 2>&1
check "with without -- and a command is a usage error" "$?" "2"
git-locks with --job w6 --holder hw -- echo x >/dev/null 2>&1
check "with without a path is a usage error" "$?" "2"
got="$(refs "${R}" jobs/w6)"
check "a usage error in with leaves no lock" "${got}" ""

# ---------------------------------------------------------------- outside a git repository

D="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-plain.XXXXXX")"
cd "${D}" || exit 2
here="$(pwd)"
got="$(git-locks --text store 2>&1)"
check "outside a repository the store is keyed on the directory" "${got}" "${HOME}/.git-stunts/locks${here}"
git-locks claim --job p1 --holder hp file.txt >/dev/null 2>&1
check "claim works outside a git repository" "$?" "0"
git-locks check file.txt >/dev/null 2>&1
check "check sees it" "$?" "1"
git-locks release --job p1 >/dev/null 2>&1
check "release works outside a git repository" "$?" "0"
GIT_LOCKS_STORE=self git-locks list >/dev/null 2>&1
check "self store outside a repository is refused with 2" "$?" "2"

# ---------------------------------------------------------------- parent/child: a child lives and dies with its parent

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job parent --holder hp p.md >/dev/null 2>&1
out="$(git-locks claim --job kid --parent parent --holder hp k.md 2>&1)"
check "a child claim under a live parent by the same holder exits 0" "$?" "0"
contains "the claim line carries the parent" "${out}" '"parent":"parent"'
valid "claim line with parent" "${out}"
out="$(git-locks show --job kid 2>&1)"
contains "show carries the parent" "${out}" '"parent":"parent"'
valid "show line with parent" "${out}"
out="$(git-locks list 2>&1)"
valid "list lines with and without parent" "${out}"
err="$(git-locks claim --job orphan --parent nope --holder hp o.md 2>&1 >/dev/null)"
check "a child claim under a missing parent exits 1" "$?" "1"
contains "the refusal names the missing parent" "${err}" '"event":"refused","reason":"parent","job":"orphan","parent":"nope","detail":"missing"'
valid "parent refusal line" "${err}"
err="$(git-locks claim --job stranger --parent parent --holder other s.md 2>&1 >/dev/null)"
check "a child claim under another holder's parent exits 1" "$?" "1"
contains "the refusal says the holder differs" "${err}" '"detail":"holder"'
got="$(refs "${R}" jobs/)"
check "refused children leave no refs" "${got}" "refs/locks/jobs/kid
refs/locks/jobs/parent"
git-locks release --job kid >/dev/null 2>&1
git-locks show --job parent >/dev/null 2>&1
check "releasing the child leaves the parent" "$?" "0"
git-locks claim --job kid --parent parent --holder hp k.md >/dev/null 2>&1
git-locks claim --job grandkid --parent kid --holder hp g.md >/dev/null 2>&1
out="$(git-locks release --job parent 2>&1)"
check "releasing the parent exits 0" "$?" "0"
contains "the release line counts the family" "${out}" '"event":"released","job":"parent","paths":3,"cascaded":["grandkid","kid"]'
valid "cascading release line" "${out}"
got="$(refs "${R}")"
check "releasing the parent removed every descendant, atomically" "${got}" ""

GIT_LOCKS_NOW=1000 git-locks claim --job oldp --holder hp --ttl 10 op.md >/dev/null 2>&1
GIT_LOCKS_NOW=1000 git-locks claim --job livekid --parent oldp --holder hp --ttl 100000 lk.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=2000 git-locks sweep 2>&1)"
contains "sweep of an expired parent names the child it took with it" "${out}" '"event":"swept","job":"oldp","holder":"hp","expires":1010,"cascaded":["livekid"]'
valid "cascading sweep line" "${out}"
got="$(refs "${R}" jobs/)"
check "a live child does not outlive its swept parent" "${got}" ""

# ---------------------------------------------------------------- several locks at once, or none at all

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job a --holder h a.md >/dev/null 2>&1
git-locks claim --job b --holder h b.md >/dev/null 2>&1
git-locks claim --job c --holder h c.md >/dev/null 2>&1
out="$(git-locks release --job a --job b 2>&1)"
check "release with several --job exits 0" "$?" "0"
lines n "${out}"
check "release with several --job emits one line per job" "${n}" "2"
got="$(refs "${R}" jobs/)"
check "both were released in one transaction and the third remains" "${got}" "refs/locks/jobs/c"

spec='job: x
holder: hx
ttl: 100
paths:
x1.md
x2.md

job: y
holder: hy
parent: x
paths:
y1.md
'
out="$(printf '%s' "${spec}" | git-locks batch 2>&1)"
check "batch claims every lock in the spec, exit 0" "$?" "0"
lines n "${out}"
check "batch emits one claimed line per lock" "${n}" "2"
contains "batch honoured the per-lock ttl" "${out}" '"job":"x","holder":"hx","claimed":1000000,"expires":1000100'
contains "batch let a child name a parent claimed in the same batch" "${out}" '"job":"y","holder":"hy"'
valid "batch claim lines" "${out}"
got="$(refs "${R}" jobs/)"
check "batch created both job refs" "${got}" "refs/locks/jobs/c
refs/locks/jobs/x
refs/locks/jobs/y"

spec2='job: m
holder: hm
paths:
m.md

job: n
holder: hn
paths:
c.md
'
err="$(printf '%s' "${spec2}" | git-locks batch 2>&1 >/dev/null)"
check "a batch with one held path is refused, exit 1" "$?" "1"
contains "the batch refusal names the holder of the held path" "${err}" '"event":"refused","path":"c.md","holder":"h","job":"c"'
git-locks check m.md >/dev/null 2>&1
check "and the free path in that batch was not taken: none at all" "$?" "0"
printf 'job: bad name\nholder: h\npaths:\nz.md\n' | git-locks batch >/dev/null 2>&1
check "a batch with a malformed record is a usage error, exit 2" "$?" "2"
printf '' | git-locks batch >/dev/null 2>&1
check "an empty batch is a usage error" "$?" "2"

# ---------------------------------------------------------------- semaphores: capacity, not exclusivity

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks sem create gpu --capacity 2 2>&1)"
check "sem create exits 0" "$?" "0"
check "sem create is one JSON line" "${out}" '{"event":"created","semaphore":"gpu","capacity":2}'
valid "sem create line" "${out}"
git-locks sem create gpu --capacity 2 >/dev/null 2>&1
check "creating a semaphore twice exits 1" "$?" "1"
git-locks sem create bad --capacity 0 >/dev/null 2>&1
check "capacity must be positive: exit 2" "$?" "2"
git-locks sem acquire nope --job j --holder h >/dev/null 2>&1
check "acquiring a missing semaphore exits 1" "$?" "1"

out="$(git-locks sem acquire gpu --job a --holder ha 2>&1)"
check "first acquire exits 0" "$?" "0"
contains "acquire line names the slot taken" "${out}" '{"event":"acquired","semaphore":"gpu","job":"a","holder":"ha","claimed":1000000,"expires":1014400,"live":1,"capacity":2}'
valid "acquire line" "${out}"
git-locks sem acquire gpu --job b --holder hb >/dev/null 2>&1
check "second acquire fills the semaphore" "$?" "0"
err="$(git-locks sem acquire gpu --job c --holder hc 2>&1 >/dev/null)"
check "a third acquire is refused with exit 1" "$?" "1"
check "the refusal says capacity, with the numbers" "${err}" '{"event":"refused","reason":"capacity","semaphore":"gpu","capacity":2,"live":2}'
valid "capacity refusal line" "${err}"
out="$(git-locks sem acquire gpu --job a --holder ha 2>&1)"
check "re-acquiring a slot the job already holds exits 0 and does not consume another" "$?" "0"
contains "re-acquire reports live unchanged" "${out}" '"live":2,"capacity":2'

out="$(git-locks sem show gpu 2>&1)"
check "sem show exits 0" "$?" "0"
contains "sem show carries capacity and live" "${out}" '{"semaphore":"gpu","capacity":2,"live":2,"slots":['
contains "sem show lists each holder with remaining" "${out}" '{"job":"a","holder":"ha","claimed":1000000,"expires":1014400,"remaining":14400}'
valid "sem show line" "${out}"
out="$(git-locks --text sem show gpu 2>&1)"
contains "--text sem show is readable" "${out}" "gpu: 2/2 slots live"
out="$(git-locks sem list 2>&1)"
contains "sem list streams one line per semaphore" "${out}" '{"semaphore":"gpu","capacity":2,"live":2'
valid "sem list line" "${out}"

out="$(git-locks sem release gpu --job a 2>&1)"
check "sem release exits 0" "$?" "0"
check "sem release is one JSON line" "${out}" '{"event":"released","semaphore":"gpu","job":"a","live":1,"capacity":2}'
valid "sem release line" "${out}"
git-locks sem acquire gpu --job c --holder hc >/dev/null 2>&1
check "the freed slot can be taken" "$?" "0"
out="$(git-locks sem release gpu --job zzz 2>&1)"
check "releasing a slot the job does not hold exits 0" "$?" "0"
contains "and says nothing was held" "${out}" '{"event":"nothing","semaphore":"gpu","job":"zzz"}'

GIT_LOCKS_NOW=1000 git-locks sem create batch --capacity 1 >/dev/null 2>&1
GIT_LOCKS_NOW=1000 git-locks sem acquire batch --job old --holder ho --ttl 10 >/dev/null 2>&1
GIT_LOCKS_NOW=1005 git-locks sem acquire batch --job new --holder hn >/dev/null 2>&1
check "a live slot blocks at capacity" "$?" "1"
out="$(GIT_LOCKS_NOW=2000 git-locks sem acquire batch --job new --holder hn 2>&1)"
check "an expired slot frees its capacity" "$?" "0"
contains "the expired slot was evicted, live is 1 not 2" "${out}" '"live":1,"capacity":1'
out="$(GIT_LOCKS_NOW=2000 git-locks sem show batch 2>&1)"
contains "show no longer lists the evicted job" "${out}" '"slots":[{"job":"new"'

GIT_LOCKS_NOW=2000 git-locks sem delete batch >/dev/null 2>&1
check "deleting a semaphore with live slots exits 1" "$?" "1"
GIT_LOCKS_NOW=2000 git-locks sem release batch --job new >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=2000 git-locks sem delete batch 2>&1)"
check "deleting an empty semaphore exits 0" "$?" "0"
check "sem delete is one JSON line" "${out}" '{"event":"deleted","semaphore":"batch"}'
valid "sem delete line" "${out}"
git-locks sem show batch >/dev/null 2>&1
check "a deleted semaphore is gone" "$?" "1"

# exactly K winners under contention
git-locks sem create race --capacity 3 >/dev/null 2>&1
wins=0
pids=()
for i in $(seq 1 20); do
  (git-locks sem acquire race --job "r${i}" --holder "h${i}" >/dev/null 2>&1) &
  pids+=($!)
done
for pid in "${pids[@]}"; do
  if wait "${pid}"; then wins=$((wins + 1)); fi
done
check "twenty racers on capacity three: exactly three win" "${wins}" "3"
out="$(git-locks sem show race 2>&1)"
contains "and the semaphore agrees" "${out}" '"capacity":3,"live":3'

# with --sem: take a slot, run, release
git-locks sem create pool --capacity 1 >/dev/null 2>&1
out="$(git-locks with --sem pool --job w --holder hw -- sh -c 'git-locks --text sem show pool | head -n 1; echo ran' 2>/dev/null)"
check "with --sem exits with the command's status" "$?" "0"
contains "the slot was held while the command ran" "${out}" 'pool: 1/1 slots live'
contains "the command ran" "${out}" "ran"
out="$(git-locks sem show pool 2>&1)"
contains "with --sem released the slot afterwards" "${out}" '"live":0'
git-locks sem acquire pool --job other --holder ho >/dev/null 2>&1
git-locks with --sem pool --job w2 --holder hw -- echo never >/dev/null 2>&1
check "with --sem at capacity exits 1 without --wait" "$?" "1"

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
if ((FAIL > 0)); then
  printf 'failed: %s\n' "${FAILED[@]}"
  exit 1
fi
