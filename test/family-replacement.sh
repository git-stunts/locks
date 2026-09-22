# shellcheck shell=bash
# Sourced by test.sh. Expected outcomes come from the public family policy,
# not the production descendants walker. Removing admission checks must fail
# these cases before doctor is allowed to diagnose an already-created graph.

family_refs() {
  local family_store family_line
  family_line="$(git-locks store)"
  jstr family_store "${family_line}" store
  git --git-dir="${family_store}" for-each-ref --format='%(refname) %(objectname)'
}

family_ok() {
  local family_out
  family_out="$(git-locks doctor 2>&1)"
  check "$1 leaves a healthy family" "$?" 0
  jfields "$1 has no invariant findings" "${family_out}" 'healthy=true' 'findings=0'
}

family_acq='' family_renewed='' family_new=''
R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job P --holder alice p.md >/dev/null
git-locks claim --job C --holder alice --parent P c.md >/dev/null
git-locks claim --job G --holder alice --parent C g.md >/dev/null
before="$(family_refs)"
out="$(git-locks claim --job P --holder alice --parent 'bad parent' p.md 2>&1)"
check "invalid parent input is a usage error even when replacement is blocked" "$?" 2
got="$(family_refs)"
check "invalid parent input preserves every ref" "${got}" "${before}"
for parent in P C G; do
  out="$(git-locks claim --job P --holder alice --parent "${parent}" p.md 2>&1)"
  check "replacement under ${parent} refuses a family cycle" "$?" 1
  got="$(family_refs)"
  check "refused cycle under ${parent} preserves every ref" "${got}" "${before}"
done
for holder in alice bob; do
  out="$(git-locks claim --job P --holder "${holder}" p.md 2>&1)"
  check "parent replacement by ${holder} refuses while descendants exist" "$?" 1
  jfields "parent replacement by ${holder} explains descendants" "${out}" 'event="refused"' 'reason="parent"' 'detail="descendants"'
  valid "parent replacement by ${holder} refusal" "${out}"
  got="$(family_refs)"
  check "refused replacement by ${holder} preserves every ref" "${got}" "${before}"
done
out="$(git-locks show --job P)"
jstr family_acq "${out}" acquisition
out="$(git-locks extend --job P --ttl 15000 2>&1)"
check "a parent with descendants can renew" "$?" 0
out="$(git-locks show --job P)"
jstr family_renewed "${out}" acquisition
check "parent renewal retains acquisition identity" "${family_renewed}" "${family_acq}"
family_ok renewal
out="$(git-locks release --job P --acquisition "${family_acq}" 2>&1)"
check "release after renewal removes the original acquisition" "$?" 0
got="$(family_refs)"
check "release removes every descendant" "${got}" ''
out="$(git-locks claim --job P --holder bob p.md 2>&1)"
check "released parent name can be recreated by another holder" "$?" 0
jstr family_new "${out}" acquisition
family_fresh=0
[[ "${family_new}" != "${family_acq}" ]] && family_fresh=1
check "recreated parent starts a fresh acquisition" "${family_fresh}" 1
out="$(git-locks claim --job P --holder bob --parent P p.md 2>&1)"
check "leaf replacement cannot parent itself" "$?" 1
valid "self-parent refusal" "${out}"
family_ok recreation

# Expired unswept descendants still belong to the acquisition.
git-locks claim --job C --holder bob --parent P --ttl 1 c.md >/dev/null
before="$(family_refs)"
out="$(GIT_LOCKS_NOW=1000002 git-locks claim --job P --holder bob p.md 2>&1)"
check "expired stored descendants still prevent parent replacement" "$?" 1
got="$(family_refs)"
check "expired-descendant refusal preserves every ref" "${got}" "${before}"
GIT_LOCKS_NOW=1000002 git-locks sweep >/dev/null
out="$(git-locks claim --job P --holder alice p.md 2>&1)"
check "sweeping the last descendant permits leaf replacement" "$?" 0
family_ok sweep

# A fresh acquisition can be followed by new children in the same batch.
R="$(mkrepo)"
cd "${R}" || exit 2
git-locks claim --job P --holder alice p.md >/dev/null
out="$(printf 'job: P\nholder: bob\npaths:\np.md\n\njob: C\nholder: bob\nparent: P\npaths:\nc.md\n' | git-locks batch 2>&1)"
check "batch replaces a leaf then attaches a child to its new acquisition" "$?" 0
family_ok batch
before="$(family_refs)"
out="$(printf 'job: P\nholder: bob\npaths:\np.md\n\njob: C\nholder: bob\nparent: P\npaths:\nc.md\n' | git-locks batch 2>&1)"
check "batch cannot replace a parent with stored descendants" "$?" 1
got="$(family_refs)"
check "refused batch replacement preserves every ref" "${got}" "${before}"

git-locks release --job P >/dev/null
git-locks claim --job P --holder alice p.md >/dev/null
before="$(family_refs)"
out="$(printf 'job: C\nholder: alice\nparent: P\npaths:\nc.md\n\njob: P\nholder: alice\npaths:\np.md\n' | git-locks batch 2>&1)"
check "batch cannot replace a parent after planning its child" "$?" 1
got="$(family_refs)"
check "refused earlier-child batch preserves every ref" "${got}" "${before}"
out="$(printf 'job: C\nholder: alice\nparent: P\npaths:\nc.md\n\njob: P\nholder: alice\nparent: C\npaths:\np.md\n' | git-locks batch 2>&1)"
check "batch cannot cycle through an earlier planned child" "$?" 1
got="$(family_refs)"
check "refused batch cycle preserves every ref" "${got}" "${before}"

# Both admitted changes use real Git transactions. Pauses only choose the
# schedule, and assertions inspect statuses, identities and final refs.
FAMILY_OUT="$(mktemp "${TMPDIR:-/tmp}/git-locks-family-out.XXXXXX")"
for first in replacement child; do
  R="$(mkrepo)"
  cd "${R}" || exit 2
  git-locks claim --job P --holder alice p.md >/dev/null
  GATE="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-family-gate.XXXXXX")/go"
  if [[ "${first}" == replacement ]]; then
    GIT_LOCKS_PAUSE_BEFORE_COMMIT="${GATE}" git-locks claim --job P --holder bob p.md >"${FAMILY_OUT}" 2>&1 &
    family_pid=$!
    reached "${GATE}"
    git-locks claim --job C --holder alice --parent P c.md >/dev/null
    check "child wins while parent replacement is paused" "$?" 0
  else
    GIT_LOCKS_PAUSE_BEFORE_COMMIT="${GATE}" git-locks claim --job C --holder alice --parent P c.md >"${FAMILY_OUT}" 2>&1 &
    family_pid=$!
    reached "${GATE}"
    git-locks claim --job P --holder bob p.md >/dev/null
    check "parent replacement wins while child admission is paused" "$?" 0
  fi
  : >"${GATE}"
  wait "${family_pid}"
  check "paused ${first} re-plans and refuses after its competing commit" "$?" 1
  family_ok "${first} race"
done

# The model derives expected admission and complete state independently of
# production parsing, doctor and descendants; each failure reports seed/step.
FAMILY_TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${FAMILY_TEST_DIR}/family-model.py" "${FAMILY_TEST_DIR}/../bin/git-locks"
check "192 seeded family operations match an independent state model" "$?" 0
