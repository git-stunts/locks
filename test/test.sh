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

# A git hook exports GIT_DIR and friends; inherited here, every git call in a
# temporary repository below would target the hook's repository instead.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX GIT_OBJECT_DIRECTORY GIT_NAMESPACE

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

jval() { # VAR JSON-LINE KEY: the raw JSON value of KEY at the top level of the first object that has it (string with quotes, number, array, literal), or empty
  local line="$2" key="$3" val=''
  if [[ "${line}" =~ \"${key}\":(\"([^\"\\]|\\.)*\"|-?[0-9]+|\[[^]]*\]|true|false|null) ]]; then
    val="${BASH_REMATCH[1]}"
  fi
  printf -v "$1" '%s' "${val}"
}

jfields() { # label JSON-LINE key=value... : each key's raw JSON value equals the expectation, in any key order
  local label="$1" line="$2" pair key want got ok=1 missing=''
  shift 2
  for pair in "$@"; do
    key="${pair%%=*}"
    want="${pair#*=}"
    jval got "${line}" "${key}"
    if [[ "${got}" != "${want}" ]]; then
      ok=0
      missing+=" ${key}: got ${got:-<absent>}, want ${want};"
    fi
  done
  if ((ok)); then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "${label}"
  else
    FAIL=$((FAIL + 1))
    FAILED+=("${label}")
    printf '  FAIL %s\n       line: %q\n       mismatch:%s\n' "${label}" "${line}" "${missing}"
  fi
}

jstr() { # VAR JSON-LINE KEY: the string value of KEY (first occurrence), or empty
  local line="$2" key="$3" val=''
  [[ "${line}" =~ \"${key}\":\"([^\"]*)\" ]] && val="${BASH_REMATCH[1]}"
  printf -v "$1" '%s' "${val}"
}

refs() { # subject-repo [prefix] -> refs in whatever store resolves for it
  local store line
  line="$(cd "$1" && git-locks store)" || return 1
  jstr store "${line}" store
  git --git-dir="${store}" for-each-ref --format='%(refname)' "refs/locks/${2:-}" | sort
}

export GIT_LOCKS_NOW=1000000
REAL_HOME="${HOME}"
HOME="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-home.XXXXXX")"
export HOME
unset GIT_LOCKS_STORE GIT_LOCKS_HOME
# Never under the operator's home: every store this suite creates lives in the throwaway HOME above.
case "${HOME}/" in
  "${REAL_HOME}/"*)
    printf 'test.sh: refusing to run with HOME under %s\n' "${REAL_HOME}" >&2
    exit 2
    ;;
  *) ;;
esac

# ---------------------------------------------------------------- claim / check / list

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks claim --job j1 --holder alice notes/x.md 'briefs/2026-09-15/y z.md' 2>&1)"
rc=$?
check "claim exits 0" "${rc}" "0"
jfields "claim prints the holder" "${out}" 'holder="alice"'
got="$(refs "${R}" | wc -l | tr -d ' ')"
check "claim writes one job ref and one ref per path" "${got}" "3"
got="$(refs "${R}" jobs/)"
check "the job ref exists" "${got}" "refs/locks/jobs/j1"

out="$(git-locks check notes/x.md 2>&1)"
rc=$?
check "check on a held path exits 1" "${rc}" "1"
contains "check names the holder" "${out}" "alice"
contains "check names the job" "${out}" "j1"

out="$(git-locks check notes/free.md 2>&1)"
rc=$?
check "check on a free path exits 0" "${rc}" "0"
jfields "check says free" "${out}" 'state="free"'

out="$(git-locks check 'briefs/2026-09-15/y z.md' 2>&1)"
check "a path with a space is held" "$?" "1"

out="$(git-locks check ./notes/x.md 2>&1)"
check "a leading ./ names the same path" "$?" "1"

out="$(git-locks list 2>&1)"
contains "list shows the holder" "${out}" "alice"
contains "list shows the job" "${out}" "j1"
contains "list shows the path with the space" "${out}" "briefs/2026-09-15/y z.md"

# ---------------------------------------------------------------- conflict / disjoint / re-claim

out="$(git-locks claim --job j2 --holder bob notes/x.md 2>&1)"
rc=$?
check "overlapping claim by another job exits 1" "${rc}" "1"
contains "overlapping claim names the holder" "${out}" "alice"
contains "overlapping claim names the path" "${out}" "notes/x.md"
got="$(refs "${R}" jobs/j2)"
check "a refused claim leaves no job ref behind" "${got}" ""

out="$(git-locks claim --job j2 --holder bob notes/other.md 2>&1)"
check "a disjoint claim by another job exits 0" "$?" "0"
got="$(refs "${R}" | wc -l | tr -d ' ')"
check "two jobs, three paths" "${got}" "5"

out="$(git-locks claim --job j1 --holder alice notes/x.md notes/added.md 2>&1)"
check "re-claim by the same job exits 0" "$?" "0"
git-locks check 'briefs/2026-09-15/y z.md' >/dev/null 2>&1
check "re-claim frees the path no longer listed" "$?" "0"
git-locks check notes/added.md >/dev/null 2>&1
check "re-claim holds the path newly listed" "$?" "1"

out="$(git-locks claim --job j2 --holder bob notes/added.md 2>&1)"
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
jfields "release of a missing lock says so" "${out}" 'event="nothing"'

# ---------------------------------------------------------------- expiry

R="$(mkrepo)"
cd "${R}" || exit 2
GIT_LOCKS_NOW=1000 git-locks claim --job old --holder bob --ttl 100 notes/e.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=1050 git-locks check notes/e.md 2>&1)"
check "before expiry the path is held" "$?" "1"
out="$(GIT_LOCKS_NOW=1200 git-locks check notes/e.md 2>&1)"
rc=$?
check "after expiry the path is free" "${rc}" "0"
jfields "after expiry check still names the expired holder" "${out}" 'state="expired"'
contains "after expiry check names who held it" "${out}" "bob"
out="$(GIT_LOCKS_NOW=1200 git-locks list 2>&1)"
jfields "list marks the lock expired" "${out}" 'state="expired"'
out="$(GIT_LOCKS_NOW=1200 git-locks claim --job new --holder alice notes/e.md 2>&1)"
check "a claim over an expired lock succeeds" "$?" "0"
got="$(refs "${R}" jobs/)"
check "the expired job ref is evicted by the claim" "${got}" "refs/locks/jobs/new"
out="$(GIT_LOCKS_NOW=1050 git-locks claim --job other --holder bob notes/e.md 2>&1)"
check "the new lock is held again" "$?" "1"

GIT_LOCKS_NOW=1000 git-locks claim --job sweepme --holder bob --ttl 10 notes/s.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=5000 git-locks sweep 2>&1)"
check "sweep exits 0" "$?" "0"
jfields "sweep names what it removed" "${out}" 'event="swept"' 'job="sweepme"'
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
line="$(git-locks store)"
jstr got "${line}" store
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
line="$(GIT_LOCKS_STORE=self git-locks store)"
jstr got "${line}" store
check "GIT_LOCKS_STORE=self resolves to the subject's own git dir" "${got}" "${common}"
GIT_LOCKS_STORE=self git-locks claim --job s --holder h self.md >/dev/null 2>&1
got="$(git -C "${R}" for-each-ref --format='%(refname)' refs/locks/jobs/)"
check "self mode writes refs into the subject repo" "${got}" "refs/locks/jobs/s"
GIT_LOCKS_STORE=self git-locks check a.md >/dev/null 2>&1
check "self mode does not see the default store's locks" "$?" "0"

custom="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-store.XXXXXX")/store"
git config locks.store "${custom}"
line="$(git-locks store)"
jstr got "${line}" store
check "git config locks.store picks a custom store path" "${got}" "${custom}"
git-locks claim --job c --holder h custom.md >/dev/null 2>&1
bare="$(git --git-dir="${custom}" rev-parse --is-bare-repository)"
check "the custom store is created bare on first use" "${bare}" "true"
line="$(GIT_LOCKS_STORE=self git-locks store)"
jstr got "${line}" store
check "the environment overrides the config" "${got}" "${common}"
git config --unset locks.store
line="$(GIT_LOCKS_HOME=/tmp/elsewhere git-locks store)"
jstr got "${line}" store
check "GIT_LOCKS_HOME relocates the default store root" "${got}" "/tmp/elsewhere/locks${top}"
git-locks store extra >/dev/null 2>&1
check "store takes no arguments" "$?" "2"

# ---------------------------------------------------------------- the CLI surface: JSON Lines, always

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks --help 2>&1)"
check "--help exits 0" "$?" "0"
contains "--help is a usage object" "${out}" '{"event":"usage","usage":"usage: git locks claim'
out="$(git-locks help 2>&1)"
check "help exits 0" "$?" "0"
git-locks >/dev/null 2>&1
check "no arguments is still a usage error, exit 2" "$?" "2"
out="$(git-locks version 2>&1)"
check "version exits 0" "$?" "0"
contains "version is JSON by default" "${out}" '{"name":"git-locks","version":"'
rc=1
[[ "${out}" =~ \"version\":\"[0-9]+\.[0-9]+\.[0-9]+\" ]] && rc=0
check "version carries a semver" "${rc}" "0"
out="$(git-locks claim --help 2>&1)"
check "claim --help exits 0" "$?" "0"
contains "claim --help shows claim's own usage" "${out}" "--holder"

jsonl_ok() { python3 -c 'import json,sys; [json.loads(l) for l in sys.stdin if l.strip()]'; }

out="$(git-locks claim --job jj --holder hh 'a b.md' c.md 2>&1)"
lines n "${out}"
check "claim is one JSON line" "${n}" "1"
jfields "claim line carries the event" "${out}" 'event="claimed"'
jfields "claim line carries the paths as an array" "${out}" 'paths=["a b.md","c.md"]'
jsonl_ok <<<"${out}" >/dev/null 2>&1
check "claim line parses as JSON" "$?" "0"
valid "claim line" "${out}"

out="$(git-locks check 'a b.md' free.md c.md 2>/dev/null)"
check "check still exits 1 when a path is held" "$?" "1"
lines n "${out}"
check "check streams one line per path" "${n}" "3"
contains "check line carries the path with its space" "${out}" '"path":"a b.md","state":"held","holder":"hh","job":"jj","expires":'
line="$(grep -F '"path":"free.md"' <<<"${out}")"
jfields "check reports the free path as free" "${line}" 'path="free.md"' 'state="free"'
jsonl_ok <<<"${out}" >/dev/null 2>&1
check "check lines parse as JSON" "$?" "0"
valid "check lines (held and free)" "${out}"

err="$(git-locks claim --job other --holder oo 'a b.md' c.md 2>&1 >/dev/null)"
lines n "${err}"
check "a refused claim streams one refusal line per held path on stderr" "${n}" "2"
jfields "refusal line names the holder" "${err}" 'event="refused"' 'path="a b.md"' 'holder="hh"' 'job="jj"'
jsonl_ok <<<"${err}" >/dev/null 2>&1
check "refusal lines parse as JSON" "$?" "0"
valid "refusal lines" "${err}"

out="$(git-locks list 2>&1)"
lines n "${out}"
check "list streams one line per lock" "${n}" "1"
contains "list line carries job, holder, state" "${out}" '{"job":"jj","holder":"hh","state":"live","claimed":'
jfields "list line carries the paths as an array" "${out}" 'paths=["a b.md","c.md"]'
jsonl_ok <<<"${out}" >/dev/null 2>&1
check "list line parses as JSON" "$?" "0"
valid "list line" "${out}"

out="$(git-locks release --job jj 2>&1)"
jfields "release is one JSON line" "${out}" 'event="released"' 'job="jj"' 'paths=2'
valid "release line" "${out}"
out="$(git-locks release --job jj 2>&1)"
valid "release-nothing line" "${out}"
out="$(git-locks list 2>&1)"
check "list with no locks streams nothing" "${out}" ""
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
lines n "${out}"
check "schema is one line" "${n}" "1"
python3 -c 'import json,sys; a=json.loads(sys.argv[1]); b=json.load(open(sys.argv[2])); sys.exit(0 if a==b else 1)' "${out}" "${SCHEMA_FILE}" >/dev/null 2>&1
check "schema output is the same document as schema/git-locks.schema.json" "$?" "0"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "${SCHEMA_FILE}" >/dev/null 2>&1
check "the schema file is valid JSON" "$?" "0"

# Streaming: the first line arrives before the last path is examined.
first="$( (
  git-locks check one.md two.md three.md 2>/dev/null
  true
) | head -n 1)"
jfields "the first check line is a complete object on its own" "${first}" 'path="one.md"' 'state="free"'

# ---------------------------------------------------------------- see everything: show, ttl, extend, remaining

R="$(mkrepo)"
cd "${R}" || exit 2
GIT_LOCKS_NOW=1000 git-locks claim --job s1 --holder hs --ttl 500 one.md two.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=1100 git-locks show --job s1 2>&1)"
check "show exits 0 for a live lock" "$?" "0"
jfields "show carries the state and remaining seconds" "${out}" 'job="s1"' 'holder="hs"' 'state="live"' 'claimed=1000' 'expires=1500' 'remaining=400' 'paths=["one.md","two.md"]'
valid "show line" "${out}"
out="$(GIT_LOCKS_NOW=2000 git-locks show --job s1 2>&1)"
check "show exits 0 for an expired lock too" "$?" "0"
jfields "show reports expired with remaining 0" "${out}" 'state="expired"' 'claimed=1000' 'expires=1500' 'remaining=0'
err="$(git-locks show --job nope 2>&1 >/dev/null)"
check "show exits 1 for a missing lock" "$?" "1"
jfields "show missing is a JSON line on stderr" "${err}" 'event="missing"' 'job="nope"'
valid "missing line" "${err}"

out="$(GIT_LOCKS_NOW=1100 git-locks ttl --job s1 2>&1)"
check "ttl exits 0" "$?" "0"
check "ttl is one JSON line with the remaining seconds" "${out}" '{"job":"s1","expires":1500,"remaining":400}'
valid "ttl line" "${out}"
git-locks ttl --job nope >/dev/null 2>&1
check "ttl exits 1 for a missing lock" "$?" "1"

out="$(GIT_LOCKS_NOW=1100 git-locks extend --job s1 --ttl 1000 2>&1)"
check "extend exits 0" "$?" "0"
jfields "extend reports the new expiry" "${out}" 'event="extended"' 'job="s1"' 'expires=2100'
valid "extend line" "${out}"
out="$(GIT_LOCKS_NOW=1100 git-locks ttl --job s1 2>&1)"
jfields "extend moved the expiry" "${out}" 'remaining=1000'
GIT_LOCKS_NOW=1100 git-locks check one.md >/dev/null 2>&1
check "extend keeps every path held" "$?" "1"
git-locks extend --job nope --ttl 5 >/dev/null 2>&1
check "extend exits 1 for a missing lock" "$?" "1"

out="$(GIT_LOCKS_NOW=1100 git-locks list 2>&1)"
jfields "list lines carry remaining seconds" "${out}" 'remaining=1000'
valid "list line with remaining" "${out}"
out="$(GIT_LOCKS_NOW=1100 git-locks check one.md 2>&1)"
jfields "check lines carry remaining seconds" "${out}" 'remaining=1000'
valid "check line with remaining" "${out}"

# ---------------------------------------------------------------- with: claim, run, release

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks with --job w1 --holder hw a.md -- sh -c 'git-locks check a.md; echo ran' 2>/dev/null)"
rc=$?
check "with exits with the command's status (0)" "${rc}" "0"
jfields "the command ran while the path was held" "${out}" 'path="a.md"' 'state="held"' 'holder="hw"' 'job="w1"'
contains "the command's stdout passes through untouched" "${out}" "ran"
git-locks check a.md >/dev/null 2>&1
check "with released the lock afterwards" "$?" "0"
err="$(git-locks with --job w1 --holder hw a.md -- true 2>&1 >/dev/null)"
jfields "with reports its own claim on stderr, not stdout" "${err}" 'event="claimed"' 'job="w1"'
line="$(grep -F '"event":"released"' <<<"${err}")"
jfields "with reports its release on stderr" "${line}" 'event="released"' 'job="w1"'
valid "with lifecycle lines" "${err}"
git-locks with --job w2 --holder hw b.md -- sh -c 'exit 7' >/dev/null 2>&1
check "with propagates a non-zero exit status" "$?" "7"
git-locks check b.md >/dev/null 2>&1
check "with releases even when the command fails" "$?" "0"
git-locks claim --job holder --holder other c.md >/dev/null 2>&1
err="$(git-locks with --job w3 --holder hw c.md -- echo never 2>&1 >/dev/null)"
check "with exits 1 when the path is held and no --wait is given" "$?" "1"
jfields "with refusal names the holder" "${err}" 'event="refused"' 'path="c.md"' 'holder="other"' 'job="holder"'
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
line="$(git-locks store 2>&1)"
jstr got "${line}" store
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
jfields "the claim line carries the parent" "${out}" 'parent="parent"'
valid "claim line with parent" "${out}"
out="$(git-locks show --job kid 2>&1)"
jfields "show carries the parent" "${out}" 'parent="parent"'
valid "show line with parent" "${out}"
out="$(git-locks list 2>&1)"
valid "list lines with and without parent" "${out}"
err="$(git-locks claim --job orphan --parent nope --holder hp o.md 2>&1 >/dev/null)"
check "a child claim under a missing parent exits 1" "$?" "1"
jfields "the refusal names the missing parent" "${err}" 'event="refused"' 'reason="parent"' 'job="orphan"' 'parent="nope"' 'detail="missing"'
valid "parent refusal line" "${err}"
err="$(git-locks claim --job stranger --parent parent --holder other s.md 2>&1 >/dev/null)"
check "a child claim under another holder's parent exits 1" "$?" "1"
jfields "the refusal says the holder differs" "${err}" 'detail="holder"'
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
jfields "the release line counts the family" "${out}" 'event="released"' 'job="parent"' 'paths=3' 'cascaded=["grandkid","kid"]'
valid "cascading release line" "${out}"
got="$(refs "${R}")"
check "releasing the parent removed every descendant, atomically" "${got}" ""

GIT_LOCKS_NOW=1000 git-locks claim --job oldp --holder hp --ttl 10 op.md >/dev/null 2>&1
GIT_LOCKS_NOW=1000 git-locks claim --job livekid --parent oldp --holder hp --ttl 100000 lk.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=2000 git-locks sweep 2>&1)"
jfields "sweep of an expired parent names the child it took with it" "${out}" 'event="swept"' 'job="oldp"' 'holder="hp"' 'expires=1010' 'cascaded=["livekid"]'
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
holder: hx
parent: x
paths:
y1.md
'
out="$(printf '%s' "${spec}" | git-locks batch 2>&1)"
check "batch claims every lock in the spec, exit 0" "$?" "0"
lines n "${out}"
check "batch emits one claimed line per lock" "${n}" "2"
jfields "batch honoured the per-lock ttl" "${out}" 'job="x"' 'holder="hx"' 'claimed=1000000' 'expires=1000100'
line="$(grep -F '"job":"y"' <<<"${out}")"
jfields "batch let a child name a parent claimed in the same batch, same holder" "${line}" 'job="y"' 'holder="hx"'
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
jfields "the batch refusal names the holder of the held path" "${err}" 'event="refused"' 'path="c.md"' 'holder="h"' 'job="c"'
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
contains "acquire line names the slot taken" "${out}" '{"event":"acquired","semaphore":"gpu","job":"a","holder":"ha","claimed":1000000,"expires":1014400,"live":1,"capacity":2,"record":"'
valid "acquire line" "${out}"
git-locks sem acquire gpu --job b --holder hb >/dev/null 2>&1
check "second acquire fills the semaphore" "$?" "0"
err="$(git-locks sem acquire gpu --job c --holder hc 2>&1 >/dev/null)"
check "a third acquire is refused with exit 1" "$?" "1"
check "the refusal says capacity, with the numbers" "${err}" '{"event":"refused","reason":"capacity","semaphore":"gpu","capacity":2,"live":2}'
valid "capacity refusal line" "${err}"
out="$(git-locks sem acquire gpu --job a --holder ha 2>&1)"
check "re-acquiring a slot the job already holds exits 0 and does not consume another" "$?" "0"
jfields "re-acquire reports live unchanged" "${out}" 'live=2' 'capacity=2'

out="$(git-locks sem show gpu 2>&1)"
check "sem show exits 0" "$?" "0"
contains "sem show carries capacity and live" "${out}" '{"semaphore":"gpu","capacity":2,"live":2,"slots":['
contains "sem show lists each holder with remaining" "${out}" '{"job":"a","holder":"ha","claimed":1000000,"expires":1014400,"remaining":14400,"record":"'
valid "sem show line" "${out}"
out="$(git-locks sem list 2>&1)"
jfields "sem list streams one line per semaphore" "${out}" 'semaphore="gpu"' 'capacity=2' 'live=2'
valid "sem list line" "${out}"

out="$(git-locks sem release gpu --job a 2>&1)"
check "sem release exits 0" "$?" "0"
check "sem release is one JSON line" "${out}" '{"event":"released","semaphore":"gpu","job":"a","live":1,"capacity":2}'
valid "sem release line" "${out}"
git-locks sem acquire gpu --job c --holder hc >/dev/null 2>&1
check "the freed slot can be taken" "$?" "0"
out="$(git-locks sem release gpu --job zzz 2>&1)"
check "releasing a slot the job does not hold exits 0" "$?" "0"
jfields "and says nothing was held" "${out}" 'event="nothing"' 'semaphore="gpu"' 'job="zzz"'

GIT_LOCKS_NOW=1000 git-locks sem create batch --capacity 1 >/dev/null 2>&1
GIT_LOCKS_NOW=1000 git-locks sem acquire batch --job old --holder ho --ttl 10 >/dev/null 2>&1
GIT_LOCKS_NOW=1005 git-locks sem acquire batch --job new --holder hn >/dev/null 2>&1
check "a live slot blocks at capacity" "$?" "1"
out="$(GIT_LOCKS_NOW=2000 git-locks sem acquire batch --job new --holder hn 2>&1)"
check "an expired slot frees its capacity" "$?" "0"
jfields "the expired slot was evicted, live is 1 not 2" "${out}" 'live=1' 'capacity=1'
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
jfields "and the semaphore agrees" "${out}" 'capacity=3' 'live=3'

# with --sem: take a slot, run, release
git-locks sem create pool --capacity 1 >/dev/null 2>&1
out="$(git-locks with --sem pool --job w --holder hw -- sh -c 'git-locks sem show pool; echo ran' 2>/dev/null)"
check "with --sem exits with the command's status" "$?" "0"
jfields "the slot was held while the command ran" "${out}" 'capacity=1' 'live=1'
contains "the command ran" "${out}" "ran"
out="$(git-locks sem show pool 2>&1)"
jfields "with --sem released the slot afterwards" "${out}" 'live=0'
git-locks sem acquire pool --job other --holder ho >/dev/null 2>&1
git-locks with --sem pool --job w2 --holder hw -- echo never >/dev/null 2>&1
check "with --sem at capacity exits 1 without --wait" "$?" "1"

# ---------------------------------------------------------------- git processes: one per protocol, not per object (issue #12)

SHIM="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-shim.XXXXXX")"
REAL_GIT="$(command -v git)"
printf '#!/usr/bin/env bash\nprintf 1 >> "%s/count"\nexec "%s" "$@"\n' "${SHIM}" "${REAL_GIT}" >"${SHIM}/git"
chmod +x "${SHIM}/git"
git_count() { # runs the args with the shim first on PATH; sets n to the number of git processes spawned
  rm -f "${SHIM}/count"
  PATH="${SHIM}:${PATH}" "$@" >/dev/null 2>&1
  if [[ -f "${SHIM}/count" ]]; then
    n="$(wc -c <"${SHIM}/count")"
    n="${n//[[:space:]]/}"
  else n=0; fi
}
R="$(mkrepo)"
cd "${R}" || exit 2
for i in $(seq 1 50); do git-locks claim --job "j${i}" --holder h "p${i}.md" >/dev/null 2>&1; done
git_count git-locks list
check "list of 50 locks spawns at most 4 git processes (rev-parse, config, for-each-ref, cat-file --batch)" "$((n <= 4))" "1"
git_count git-locks check p1.md p2.md p3.md
check "check of 3 paths spawns at most 7 git processes (snapshot plus one hash-object per path)" "$((n <= 7))" "1"
git_count git-locks show --job j7
check "show spawns at most 4 git processes" "$((n <= 4))" "1"
git_count git-locks claim --job jx --holder h a.md b.md c.md
check "a 3-path claim spawns at most 10 git processes (lookup, snapshot, 3 hashes, a blob write, a transaction)" "$((n <= 10))" "1"
git-locks sem create s --capacity 5 >/dev/null 2>&1
for i in 1 2 3; do git-locks sem acquire s --job "t${i}" --holder h >/dev/null 2>&1; done
git_count git-locks sem show s
check "sem show spawns at most 4 git processes" "$((n <= 4))" "1"
out="$(git-locks list 2>&1)"
lines n "${out}"
check "the snapshot path lists every lock" "${n}" "51"
valid "list lines after the snapshot refactor" "${out}"

# ================================================================ correctness review, 2026-09-15: every finding reproduced first

# ---------------------------------------------------------------- MUST 2: one final transition per ref

R="$(mkrepo)"
cd "${R}" || exit 2
GIT_LOCKS_NOW=1000 git-locks claim --job expired-two --holder h --ttl 10 a.md b.md >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=2000 git-locks claim --job taker --holder h a.md b.md 2>&1)"
check "claiming two paths held by one expired job succeeds (the expired job ref is deleted once, not twice)" "$?" "0"
got="$(refs "${R}" jobs/)"
check "the expired job is evicted and the taker holds both" "${got}" "refs/locks/jobs/taker"

git-locks claim --job P --holder h p.md >/dev/null 2>&1
spec='job: c1
holder: h
parent: P
paths:
c1.md

job: c2
holder: h
parent: P
paths:
c2.md
'
out="$(printf '%s' "${spec}" | git-locks batch 2>&1)"
check "a batch of two children under one existing parent succeeds (the parent is verified once)" "$?" "0"
git-locks release --job P >/dev/null 2>&1
git-locks sem create s --capacity 1 >/dev/null 2>&1
GIT_LOCKS_NOW=1000 git-locks sem acquire s --job s1 --holder h --ttl 10 >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=2000 git-locks sem acquire s --job s1 --holder h 2>&1)"
check "re-acquiring an expired slot under the same job id succeeds (one transition for that slot ref)" "$?" "0"
jfields "and reports one live slot" "${out}" 'live=1' 'capacity=1'

# ---------------------------------------------------------------- MUST 1: a failed read is an error, never a free path; waits see releases

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job held --holder h x.md >/dev/null 2>&1
BROKEN="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-broken.XXXXXX")"
printf '#!/usr/bin/env bash\nif [[ " $* " == *" for-each-ref "* ]]; then echo "fatal: injected read failure" >&2; exit 128; fi\nexec "%s" "$@"\n' "${REAL_GIT}" >"${BROKEN}/git"
chmod +x "${BROKEN}/git"
out="$(PATH="${BROKEN}:${PATH}" git-locks check x.md 2>/dev/null)"
rc=$?
err="$(PATH="${BROKEN}:${PATH}" git-locks check x.md 2>&1 >/dev/null)"
check "a failed store read exits 2, not 0" "${rc}" "2"
check "a failed store read prints no path line" "${out}" ""
jfields "a failed store read is a structured error line" "${err}" 'event="error"' 'reason="store-read"'
valid "store-read error line" "${err}"

git-locks sem create w --capacity 1 >/dev/null 2>&1
git-locks sem acquire w --job other --holder o >/dev/null 2>&1
(
  sleep 1
  git-locks sem release w --job other >/dev/null 2>&1
) &
out="$(git-locks sem acquire w --job waiter --holder h --wait 10 2>&1)"
check "sem acquire --wait sees a release made during the wait (the cached read is refreshed per attempt)" "$?" "0"
wait

# ---------------------------------------------------------------- MUST 3: membership is part of the conflict boundary

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job P --holder h p.md >/dev/null 2>&1
GATE="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-gate.XXXXXX")/go"
GIT_LOCKS_PAUSE_BEFORE_COMMIT="${GATE}" git-locks release --job P >/dev/null 2>&1 &
rel=$!
sleep 1 # the release has read the family (no children) and is paused before its transaction
git-locks claim --job C --parent P --holder h c.md >/dev/null 2>&1
check "a child claim while a release is paused before commit succeeds (the parent still exists)" "$?" "0"
: >"${GATE}"
wait "${rel}"
check "the paused release still exits 0 (it re-reads after its stale plan is refused)" "$?" "0"
got="$(refs "${R}" jobs/)"
check "no child survives its parent's release: the release took C with it or was told about it" "${got}" ""

spec='job: px
holder: hx
paths:
px.md

job: cy
holder: hy
parent: px
paths:
cy.md
'
err="$(printf '%s' "${spec}" | git-locks batch 2>&1 >/dev/null)"
check "a batch child under a same-batch parent with a different holder is refused" "$?" "1"
jfields "the refusal says holder" "${err}" 'reason="parent"' 'job="cy"' 'parent="px"' 'detail="holder"'
got="$(refs "${R}" jobs/)"
check "and neither record landed" "${got}" ""

GIT_LOCKS_NOW=1000 git-locks claim --job oldp --holder h --ttl 10 op.md >/dev/null 2>&1
GIT_LOCKS_NOW=1000 git-locks claim --job kid --parent oldp --holder h --ttl 100000 k.md >/dev/null 2>&1
GIT_LOCKS_NOW=2000 git-locks claim --job newp --holder h op.md >/dev/null 2>&1
check "a claim that evicts an expired parent succeeds" "$?" "0"
got="$(GIT_LOCKS_NOW=2000 refs "${R}" jobs/)"
check "claim-time eviction of a parent cascades like release and sweep do: the live child is gone too" "${got}" "refs/locks/jobs/newp"

# ---------------------------------------------------------------- MUST 4: release the acquisition you made, not whatever wears the name now

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks claim --job build --holder A x.md 2>&1)"
contains "a claim line carries the record id of this acquisition" "${out}" '"record":"'
rec="$(printf '%s' "${out}" | sed -n 's/.*"record":"\([0-9a-f]*\)".*/\1/p')"
git-locks claim --job build --holder B y.md >/dev/null 2>&1
out="$(git-locks release --job build --record "${rec}" 2>&1)"
check "release --record of a superseded acquisition exits 0 and releases nothing" "$?" "0"
jfields "and says so" "${out}" 'event="nothing"' 'job="build"' 'reason="superseded"'
git-locks check y.md >/dev/null 2>&1
check "B's acquisition under the same job name survives A's release" "$?" "1"
git-locks with --job w --holder A z.md -- sh -c 'git-locks claim --job w --holder B other.md >/dev/null 2>&1' >/dev/null 2>&1
git-locks check other.md >/dev/null 2>&1
check "with releases only the acquisition it made: a re-claim of its job name by another holder survives" "$?" "1"
git-locks release --job w >/dev/null 2>&1

# ---------------------------------------------------------------- MUST 5: the JSON contract survives failures

R="$(mkrepo)"
cd "${R}" || exit 2
ctrl="$(printf 'h\001x')"
out="$(git-locks claim --job ctrl --holder "${ctrl}" a.md 2>&1)"
check "a control character in a holder does not break the claim" "$?" "0"
jsonl_ok <<<"${out}" >/dev/null 2>&1
check "the claim line is still valid JSON (control characters escaped)" "$?" "0"
jfields "the escape is the JSON one" "${out}" 'holder="h\u0001x"'
err="$(git-locks claim --job bad --holder h --ttl nope a.md 2>&1 >/dev/null)"
check "a usage failure still exits 2" "$?" "2"
jfields "a usage failure is a structured error line in JSON mode" "${err}" 'event="error"' 'reason="usage"'
valid "usage error line" "${err}"
BROKEN2="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-broken2.XXXXXX")"
printf '#!/usr/bin/env bash\nif [[ " $* " == *" update-ref "* ]]; then printf "fatal: injected\\nsecond line with \\"quotes\\"\\n" >&2; exit 128; fi\nexec "%s" "$@"\n' "${REAL_GIT}" >"${BROKEN2}/git"
chmod +x "${BROKEN2}/git"
err="$(PATH="${BROKEN2}:${PATH}" git-locks claim --job t --holder h t.md 2>&1 >/dev/null)"
check "a failed transaction exits 1" "$?" "1"
jsonl_ok <<<"${err}" >/dev/null 2>&1
check "a multi-line git diagnostic inside a refusal is still valid JSON" "$?" "0"
valid "transaction refusal line" "${err}"

# ---------------------------------------------------------------- SHOULD: what a path identifies

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job n1 --holder h dir/file.md >/dev/null 2>&1
git-locks check 'dir//file.md' >/dev/null 2>&1
check "dir//file.md names the same path as dir/file.md" "$?" "1"
git-locks check 'dir/./file.md' >/dev/null 2>&1
check "dir/./file.md names the same path as dir/file.md" "$?" "1"
git-locks check 'dir/file.md/' >/dev/null 2>&1
check "a trailing slash is stripped" "$?" "1"

# ---------------------------------------------------------------- acquisition identity survives renewal (review MUST 4, second half)

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(git-locks claim --job ren --holder A r.md 2>&1)"
contains "a claim line carries an acquisition id distinct from the record oid" "${out}" '"acquisition":"'
acq=''
rec=''
acq2=''
rec2=''
pacq=''
pacq2=''
jstr acq "${out}" acquisition
jstr rec "${out}" record
distinct=no
[[ -n "${acq}" && "${acq}" != "${rec}" ]] && distinct=yes
check "acquisition and record differ in kind: the acquisition is not the oid" "${distinct}" "yes"
out="$(git-locks extend --job ren --ttl 999 2>&1)"
line="$(git-locks show --job ren 2>&1)"
jstr acq2 "${line}" acquisition
jstr rec2 "${line}" record
check "extend keeps the acquisition id" "${acq2}" "${acq}"
changed=no
[[ "${rec2}" != "${rec}" ]] && changed=yes
check "extend changes the record oid" "${changed}" "yes"
out="$(git-locks release --job ren --acquisition "${acq}" 2>&1)"
check "release --acquisition after a renewal releases the lock" "$?" "0"
jfields "and reports it released" "${out}" 'event="released"' 'job="ren"'
git-locks claim --job ren --holder B other.md >/dev/null 2>&1
out="$(git-locks release --job ren --acquisition "${acq}" 2>&1)"
jfields "release --acquisition of a superseded acquisition releases nothing" "${out}" 'event="nothing"' 'job="ren"' 'reason="superseded"'
git-locks check other.md >/dev/null 2>&1
check "B's acquisition survives" "$?" "1"
git-locks release --job ren >/dev/null 2>&1

git-locks with --job w --holder A z.md -- sh -c 'git-locks extend --job w --ttl 5000 >/dev/null 2>&1' >/dev/null 2>&1
check "with exits 0 when the command renewed the lock" "$?" "0"
git-locks check z.md >/dev/null 2>&1
check "with still releases its lock after the command renewed it (release by acquisition, not by record)" "$?" "0"

# a parent renewed by extend keeps its acquisition and its children
git-locks claim --job P --holder h p.md >/dev/null 2>&1
git-locks claim --job C --parent P --holder h c.md >/dev/null 2>&1
line="$(git-locks show --job P 2>&1)"
jstr pacq "${line}" acquisition
git-locks extend --job P --ttl 7777 >/dev/null 2>&1
line="$(git-locks show --job P 2>&1)"
jstr pacq2 "${line}" acquisition
check "a parent keeps its acquisition id across a child admission and a renewal" "${pacq2}" "${pacq}"
git-locks release --job P >/dev/null 2>&1

# ---------------------------------------------------------------- forced schedule: renewal between a release's read and its commit

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job P --holder h p.md >/dev/null 2>&1
GATE="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-gate2.XXXXXX")/go"
GIT_LOCKS_PAUSE_BEFORE_COMMIT="${GATE}" git-locks release --job P >/dev/null 2>&1 &
rel=$!
sleep 1
git-locks extend --job P --ttl 4242 >/dev/null 2>&1
check "a renewal while a release is paused before commit succeeds" "$?" "0"
: >"${GATE}"
wait "${rel}"
check "the paused release still exits 0 after the renewal moved the record" "$?" "0"
got="$(refs "${R}" jobs/)"
check "and the renewed lock is gone: the release re-planned against the new record" "${got}" ""

# ---------------------------------------------------------------- forced schedule: a waiter's stale read, then a release (#23)

R="$(mkrepo)"
cd "${R}" || exit 2
git-locks sem create w3 --capacity 1 >/dev/null 2>&1
git-locks sem acquire w3 --job holder --holder o >/dev/null 2>&1
GATE3="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-gate3.XXXXXX")/go"
TRACE3="$(mktemp "${TMPDIR:-/tmp}/git-locks-trace3.XXXXXX")"
# The waiter reads (semaphore full), then pauses after that read. The holder releases. The gate opens.
GIT_LOCKS_PAUSE_AFTER_READ="${GATE3}" GIT_LOCKS_TRACE="${TRACE3}" git-locks sem acquire w3 --job waiter --holder h --wait 20 >/tmp/gl-waiter.out 2>&1 &
wpid=$!
sleep 1
git-locks sem release w3 --job holder >/dev/null 2>&1
: >"${GATE3}"
wait "${wpid}"
check "the waiter acquires after the release it could not see at first" "$?" "0"
out="$(cat /tmp/gl-waiter.out)"
jfields "the waiter's line is a real acquisition" "${out}" 'event="acquired"' 'job="waiter"' 'live=1' 'capacity=1'
reads="$(grep -c '^snapshot' "${TRACE3}")"
check "the waiter took exactly two reads: the stale one it was paused on, and one fresh read that saw the release" "${reads}" "2"
out="$(git-locks sem show w3 2>&1)"
jfields "the semaphore holds one live slot, the waiter's" "${out}" 'live=1' 'capacity=1'

# The same gate on a path lock: with --wait sees a release made after its stale read.
git-locks claim --job blocker --holder o p3.md >/dev/null 2>&1
GATE4="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-gate4.XXXXXX")/go"
TRACE4="$(mktemp "${TMPDIR:-/tmp}/git-locks-trace4.XXXXXX")"
GIT_LOCKS_PAUSE_AFTER_READ="${GATE4}" GIT_LOCKS_TRACE="${TRACE4}" git-locks with --job waiter2 --holder h --wait 20 p3.md -- sh -c "cp '${TRACE4}' '${TRACE4}.at-run'; echo ran" >/tmp/gl-waiter2.out 2>/dev/null &
wpid=$!
sleep 1
git-locks release --job blocker >/dev/null 2>&1
: >"${GATE4}"
wait "${wpid}"
check "with --wait runs its command after a release it could not see at first" "$?" "0"
ran="$(cat /tmp/gl-waiter2.out)"
check "and the command ran once" "${ran}" "ran"
reads="$(grep -c '^snapshot' "${TRACE4}.at-run")"
check "with took exactly two reads before running its command (the release afterwards is a third)" "${reads}" "2"
git-locks check p3.md >/dev/null 2>&1
check "with released its lock afterwards" "$?" "0"

# ---------------------------------------------------------------- #11: bin/git-locks is built from lib/, byte for byte

BUILT="$(mktemp "${TMPDIR:-/tmp}/git-locks-built.XXXXXX")"
(cd "${HERE}/.." && bash scripts/build.sh "${BUILT}") >/dev/null 2>&1
check "scripts/build.sh assembles the script from lib/ and the schema" "$?" "0"
cmp -s "${BUILT}" "${HERE}/../bin/git-locks"
check "the committed bin/git-locks is exactly what lib/ builds (run make build after editing lib/)" "$?" "0"
libs=("${HERE}/../lib/"*.sh)
check "lib/ has more than one module" "$((${#libs[@]} > 1))" "1"

# ---------------------------------------------------------------- #24: records are parsed once; list cost is printed, not gated

R="$(mkrepo)"
cd "${R}" || exit 2
for i in $(seq 1 200); do git-locks claim --job "l${i}" --holder h "f${i}.md" >/dev/null 2>&1; done
t0="$(date +%s)"
out="$(git-locks list 2>&1)"
t1="$(date +%s)"
lines n "${out}"
check "list renders all 200 locks" "${n}" "200"
printf '  info list of 200 locks took %ds (printed for the record; #24 tracks it, no gate)\n' "$((t1 - t0))"
TRACE5="$(mktemp "${TMPDIR:-/tmp}/git-locks-trace5.XXXXXX")"
GIT_LOCKS_TRACE="${TRACE5}" git-locks list >/dev/null 2>&1
parses="$(grep -c '^parse' "${TRACE5}")"
check "each record is parsed exactly once for a list (one parse line per blob in the trace)" "${parses}" "200"

# ---------------------------------------------------------------- review of 0.4.0: ttl is decimal, a holder is one line stored whole, sweep never deletes a renewed lock

R="$(mkrepo)"
cd "${R}" || exit 2
out="$(GIT_LOCKS_NOW=1000 git-locks claim --job oct --holder h --ttl 010 x.md 2>&1)"
check "claim --ttl 010 is ten seconds, not octal eight" "$?" "0"
out="$(GIT_LOCKS_NOW=1000 git-locks ttl --job oct 2>&1)"
jfields "and the lock expires at now + 10" "${out}" 'expires=1010'
GIT_LOCKS_NOW=1000 git-locks extend --job oct --ttl 020 >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=1000 git-locks ttl --job oct 2>&1)"
jfields "extend --ttl 020 is twenty seconds" "${out}" 'expires=1020'
out="$(GIT_LOCKS_NOW=1000 git-locks extend --job oct --ttl 08 2>&1)"
check "extend --ttl 08 is eight seconds, not an arithmetic error" "$?" "0"
out="$(GIT_LOCKS_NOW=1000 git-locks ttl --job oct 2>&1)"
jfields "and expires at now + 8" "${out}" 'expires=1008'
git-locks sem create o --capacity 1 >/dev/null 2>&1
out="$(GIT_LOCKS_NOW=1000 git-locks sem acquire o --job s --holder h --ttl 010 2>&1)"
check "sem acquire --ttl 010 is accepted" "$?" "0"
out="$(GIT_LOCKS_NOW=1000 git-locks sem show o 2>&1)"
contains "and the slot has ten seconds" "${out}" '"remaining":10'
out="$(printf 'job: b\nholder: h\nttl: 010\npaths:\nb.md\n' | GIT_LOCKS_NOW=1000 git-locks batch 2>&1)"
check "batch ttl: 010 is accepted" "$?" "0"
out="$(GIT_LOCKS_NOW=1000 git-locks ttl --job b 2>&1)"
jfields "and is ten seconds" "${out}" 'expires=1010'

out="$(printf 'parent: oct\n' | git-locks batch 2>&1)"
check "a batch record with only parent: is malformed, not silently dropped" "$?" "2"
out="$(printf 'parent: oct\n\njob: k\nholder: h\npaths:\nk.md\n' | git-locks batch 2>&1)"
check "and cannot leak its parent into the next record" "$?" "2"
git-locks show --job k >/dev/null 2>&1
check "so no lock k was made" "$?" "1"

out="$(GIT_LOCKS_NOW=1000 git-locks claim --job ctl --holder $'a\x1eexpires: 5\x1fjob\x1e' --ttl 10 c1.md 2>&1)"
check "a holder carrying bytes that look like field delimiters claims" "$?" "0"
out="$(GIT_LOCKS_NOW=1000 git-locks show --job ctl 2>&1)"
jfields "and cannot shadow a field: expires and job are the record's own" "${out}" 'expires=1010' 'job="ctl"' 'holder="a\u001eexpires: 5\u001fjob\u001e"'
valid "a show line with control bytes in the holder" "${out}"
out="$(git-locks claim --job ctl2 --holder $'two\nlines' c2.md 2>&1)"
check "a holder with a newline is refused at claim" "$?" "2"
out="$(git-locks sem acquire o --job ctl --holder $'a\nb' 2>&1)"
check "a holder with a newline is refused at sem acquire" "$?" "2"
out="$(git-locks sem acquire o --job ctl --holder $'a\rb' 2>&1)"
check "and so is a carriage return" "$?" "2"
out="$(git-locks with --job ctl2 --holder $'a\nb' c2.md -- true 2>&1)"
check "and a newline at with" "$?" "2"
git-locks check c2.md >/dev/null 2>&1
check "none of those refusals left a lock behind" "$?" "0"

out="$(LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 git-locks claim --job u --holder 'héloïse' 'café/naïve.md' 2>&1)"
check "a non-ASCII holder and path claim under a UTF-8 locale" "$?" "0"
out="$(LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 git-locks list 2>&1)"
check "and list under that locale exits 0" "$?" "0"
contains "with the holder intact" "${out}" '"holder":"héloïse"'
contains "and the path intact" "${out}" '"paths":["café/naïve.md"]'
valid "list lines with non-ASCII text" "${out}"
out="$(LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 git-locks check 'café/naïve.md' 2>&1)"
check "check sees it held" "$?" "1"

out="$(git-locks with --job z --holder h --sem o --ttl 0 -- true 2>&1)"
check "with --sem refuses --ttl 0 before acquiring anything" "$?" "2"
out="$(git-locks sem show o 2>&1)"
rc=0
[[ "${out}" != *'"job":"z"'* ]] || rc=1
check "and left no slot for it" "${rc}" "0"
out="$(git-locks with --job z --holder h --sem 'bad name' -- true 2>&1)"
check "with --sem validates the semaphore name" "$?" "2"

# A signal while with waits for the path lock must release the slot it already took.
git-locks sem create w1 --capacity 1 >/dev/null 2>&1
git-locks claim --job blocker --holder o held.md >/dev/null 2>&1
git-locks with --job waiter --holder h --sem w1 --wait 30 held.md -- true >/dev/null 2>&1 &
wpid=$!
sleep 2
kill -TERM "${wpid}" 2>/dev/null
wait "${wpid}" 2>/dev/null
out="$(git-locks sem show w1 2>&1)"
jfields "a TERM during the lock wait released the semaphore slot with had taken" "${out}" 'live=0'

# sweep: a lock renewed between sweep's read and its transaction is not deleted.
R="$(mkrepo)"
cd "${R}" || exit 2
GIT_LOCKS_NOW=1000 git-locks claim --job renew --holder h --ttl 10 r.md >/dev/null 2>&1
GATE6="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-gate6.XXXXXX")/go"
GIT_LOCKS_NOW=2000 GIT_LOCKS_PAUSE_AFTER_READ="${GATE6}" git-locks sweep >/tmp/gl-sweep.out 2>&1 &
spid=$!
sleep 1
GIT_LOCKS_NOW=2000 git-locks extend --job renew --ttl 100 >/dev/null 2>&1
: >"${GATE6}"
wait "${spid}"
check "sweep exits 0 when the expired lock it saw was renewed underneath" "$?" "0"
out="$(cat /tmp/gl-sweep.out)"
check "and sweeps nothing" "${out}" ""
out="$(GIT_LOCKS_NOW=2000 git-locks ttl --job renew 2>&1)"
jfields "the renewed lock is still there with its new expiry" "${out}" 'expires=2100'

out="$(git-locks version extra 2>&1)"
check "version takes no arguments" "$?" "2"

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
if ((FAIL > 0)); then
  printf 'failed: %s\n' "${FAILED[@]}"
  exit 1
fi
