#!/usr/bin/env bash
# Focused regression coverage for literal glob characters in path identity.
set -uo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX GIT_OBJECT_DIRECTORY GIT_NAMESPACE

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HERE}/../bin:${PATH}"
PASS=0
FAIL=0
FAILED=()
CASE_NUMBER=0

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

TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-literal-paths.XXXXXX")"
cleanup() {
  if [[ -n "${TEST_ROOT:-}" && "${TEST_ROOT}" == "${TMPDIR:-/tmp}"/git-locks-literal-paths.* ]]; then
    rm -rf -- "${TEST_ROOT}"
  fi
}
trap cleanup EXIT

export HOME="${TEST_ROOT}/home"
mkdir -p "${HOME}"
export GIT_LOCKS_NOW=1000000

new_case() {
  CASE_NUMBER=$((CASE_NUMBER + 1))
  CASE_ROOT="${TEST_ROOT}/case-${CASE_NUMBER}"
  WORK_ROOT="${CASE_ROOT}/work"
  mkdir -p "${WORK_ROOT}"
  git -C "${WORK_ROOT}" init -q -b main
  export GIT_LOCKS_STORE="${CASE_ROOT}/store.git"
  cd "${WORK_ROOT}" || exit 2
}

assert_claim_path() { # label job literal-path
  local label="$1" job="$2" path="$3" out rc
  out="$(git-locks claim --job "${job}" --holder alice "${path}" 2>&1)"
  rc=$?
  check "${label}: claim succeeds" "${rc}" "0"
  contains "${label}: claim reports the literal path" "${out}" "\"paths\":[\"${path}\"]"
}

# Golden reproduction: a matching neighbour must not change the requested key.
new_case
touch 'report[1].md' report1.md
out="$(git-locks claim --job report --holder alice 'report[1].md' 2>&1)"
check "bracket golden path: claim succeeds" "$?" "0"
contains "bracket golden path: claim reports the literal name" "${out}" '"paths":["report[1].md"]'
out="$(git-locks show --job report 2>&1)"
contains "bracket golden path: show keeps the literal name" "${out}" '"paths":["report[1].md"]'
out="$(git-locks list 2>&1)"
contains "bracket golden path: list keeps the literal name" "${out}" '"paths":["report[1].md"]'
out="$(git-locks check 'report[1].md' 2>&1)"
check "bracket golden path: the requested name is held" "$?" "1"
contains "bracket golden path: check reports the requested name" "${out}" '"path":"report[1].md"'
git-locks check report1.md >/dev/null 2>&1
check "bracket golden path: the matching neighbour stays free" "$?" "0"
err="$(git-locks claim --job contender --holder bob 'report[1].md' 2>&1 >/dev/null)"
check "bracket golden path: a contender for the literal name is refused" "$?" "1"
contains "bracket golden path: refusal names the literal resource" "${err}" '"path":"report[1].md"'
git-locks claim --job neighbour --holder bob report1.md >/dev/null 2>&1
check "bracket golden path: the matching neighbour remains claimable" "$?" "0"

# Zero, one and several filesystem matches for every glob form.
new_case
assert_claim_path "star with zero matches" star-zero 'zero*.md'

new_case
touch one-match.md
assert_claim_path "star with one match" star-one 'one*.md'

new_case
touch many-a.md many-b.md
assert_claim_path "star with several matches" star-many 'many*.md'

new_case
touch question1.md
assert_claim_path "question mark with one match" question-one 'question?.md'

new_case
assert_claim_path "brackets with zero matches" bracket-zero 'bracket[ab].md'

new_case
touch bracketa.md
assert_claim_path "brackets with one match" bracket-one 'bracket[ab].md'

new_case
touch bracketa.md bracketb.md
assert_claim_path "brackets with several matches" bracket-many 'bracket[ab].md'

# Each component is lexical. Matches in the working tree cannot rewrite nested names.
new_case
mkdir -p 'source[1]' source1
touch 'source[1]/file?.md' source1/file1.md file1.md
assert_claim_path "nested glob components" nested 'source[1]/file?.md'
git-locks check source1/file1.md >/dev/null 2>&1
check "nested glob components: the expanded neighbour stays free" "$?" "0"

# A trailing slash remains the prefix marker while the preceding bytes stay literal.
new_case
mkdir -p 'dist[1]' dist1
assert_claim_path "literal prefix" prefix 'dist[1]/'
out="$(git-locks check 'dist[1]/asset.js' 2>&1)"
check "literal prefix: a child of the requested prefix is held" "$?" "1"
contains "literal prefix: check names the literal prefix" "${out}" '"via":"dist[1]/"'
git-locks check dist1/asset.js >/dev/null 2>&1
check "literal prefix: a child of the matching neighbour stays free" "$?" "0"

# Batch takes the same literal path contract as claim.
new_case
touch batch1.md
out="$(printf 'job: batch\nholder: alice\npaths:\nbatch[1].md\n' | git-locks batch 2>&1)"
check "batch: a literal bracket path claims" "$?" "0"
contains "batch: output keeps the literal path" "${out}" '"paths":["batch[1].md"]'
out="$(git-locks show --job batch 2>&1)"
contains "batch: the stored record keeps the literal path" "${out}" '"paths":["batch[1].md"]'
git-locks check batch1.md >/dev/null 2>&1
check "batch: the matching neighbour stays free" "$?" "0"

# A later filesystem match must not change how a read resolves an existing key.
new_case
git-locks claim --job late --holder alice 'late?.md' >/dev/null 2>&1
touch late1.md
out="$(git-locks check 'late?.md' 2>&1)"
check "read after filesystem change: the literal key remains held" "$?" "1"
contains "read after filesystem change: check reports the literal key" "${out}" '"path":"late?.md"'
git-locks check late1.md >/dev/null 2>&1
check "read after filesystem change: the new matching path is free" "$?" "0"

# Existing lexical rules remain in force around literal glob bytes.
new_case
out="$(git-locks claim --job lexical --holder alice './dir//./file[1].md' 2>&1)"
check "lexical rules: claim succeeds" "$?" "0"
contains "lexical rules: dot and empty components are removed" "${out}" '"paths":["dir/file[1].md"]'
git-locks check 'dir/file[1].md' >/dev/null 2>&1
check "lexical rules: the normalized literal path is held" "$?" "1"
out="$(git-locks claim --job lexical-prefix --holder alice './prefix//./' 2>&1)"
check "lexical rules: normalized prefix claim succeeds" "$?" "0"
contains "lexical rules: a trailing slash remains" "${out}" '"paths":["prefix/"]'
git-locks claim --job absolute --holder alice '/absolute?.md' >/dev/null 2>&1
check "lexical rules: absolute paths remain refused" "$?" "2"
git-locks claim --job parent --holder alice 'a/../b?.md' >/dev/null 2>&1
check "lexical rules: parent components remain refused" "$?" "2"

# Deterministic property stress: each generated glob-shaped key has one matching
# neighbour on disk. Reserving the key must never reserve its neighbour.
new_case
FUZZ_SEED=320032
FUZZ_CASES=64
fuzz_state=${FUZZ_SEED}
for ((i = 0; i < FUZZ_CASES; i++)); do
  fuzz_state=$(((1103515245 * fuzz_state + 12345) & 0x7fffffff))
  digit=$((fuzz_state % 10))
  case $((i % 3)) in
    0)
      literal="fuzz-${i}[${digit}].lock"
      neighbour="fuzz-${i}${digit}.lock"
      ;;
    1)
      literal="fuzz-${i}-*.lock"
      neighbour="fuzz-${i}-${digit}.lock"
      ;;
    *)
      literal="fuzz-${i}-?.lock"
      neighbour="fuzz-${i}-${digit}.lock"
      ;;
  esac
  touch "${neighbour}"
  out="$(git-locks claim --job "fuzz-${i}" --holder stress "${literal}" 2>&1)"
  check "fuzz ${i}: claim succeeds" "$?" "0"
  contains "fuzz ${i}: claim preserves path identity" "${out}" "\"paths\":[\"${literal}\"]"
  git-locks check "${neighbour}" >/dev/null 2>&1
  check "fuzz ${i}: matching neighbour stays free" "$?" "0"
done
out="$(git-locks doctor 2>&1)"
check "fuzz seed ${FUZZ_SEED}: ${FUZZ_CASES} claims leave a healthy store" "$?" "0"
contains "fuzz seed ${FUZZ_SEED}: doctor reports no invariant findings" "${out}" '"healthy":true'

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
if ((FAIL > 0)); then
  printf 'failed:'
  printf ' %s;' "${FAILED[@]}"
  printf '\n'
  exit 1
fi
