#!/usr/bin/env bash
# Local integration example. It retains all artifacts in one fresh directory.
# The fixed clock makes expiry an explicit demonstration, not a timing guess.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
export DEMO_BIN="${ROOT}/bin/git-locks"
if (($# > 1)); then
  printf 'usage: bash examples/cooperating-workers/demo.sh [fresh-output-directory]\n' >&2
  exit 2
fi
if (($#)); then
  output="$1"
  if [[ -e "${output}" ]]; then
    printf 'output directory already exists: %s\n' "${output}" >&2
    exit 2
  fi
  mkdir -p "${output}"
else
  output="$(mktemp -d "${TMPDIR:-/tmp}/git-locks-workers.XXXXXX")"
fi
output="$(cd "${output}" && pwd)"
mkdir -p "${output}/work/generated" "${output}/receipts" "${output}/gates" "${output}/tmp"
export DEMO_RECEIPTS="${output}/receipts"
export GIT_LOCKS_STORE="${output}/store.git" GIT_LOCKS_NOW=1000000
export TMPDIR="${output}/tmp"
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX GIT_OBJECT_DIRECTORY GIT_NAMESPACE
children=() gates=()
cleanup() {
  local gate pid
  for gate in "${gates[@]}"; do : >"${gate}"; done
  for pid in "${children[@]}"; do wait "${pid}" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "${output}/work"
"${DEMO_BIN}" version >"${DEMO_RECEIPTS}/version.jsonl"
git -C "${ROOT}" rev-parse HEAD >"${DEMO_RECEIPTS}/source-revision.txt"
"${DEMO_BIN}" store >"${DEMO_RECEIPTS}/store.jsonl"

await_ready() { # gate pid: wait for the admitted worker's explicit ready signal
  local gate="$1" pid="$2" attempt
  for ((attempt = 0; attempt < 1500; attempt++)); do
    [[ ! -f "${gate}.ready" ]] || return 0
    if ! kill -0 "${pid}" 2>/dev/null; then
      printf 'worker exited before signalling readiness\n' >&2
      return 1
    fi
    sleep 0.02
  done
  printf 'launcher timed out waiting for worker readiness\n' >&2
  return 1
}

expect_status() { # expected command...
  local expected="$1" actual=0
  shift
  "$@" || actual=$?
  if ((actual != expected)); then
    printf 'expected exit %s, got %s: %s\n' "${expected}" "${actual}" "$*" >&2
    return 1
  fi
}

acquisition_from() { # VAR file: IDs emitted by this example are plain strings
  local line
  read -r line <"$2"
  [[ "${line}" =~ \"acquisition\":\"([^\"]+)\" ]] || return 1
  printf -v "$1" '%s' "${BASH_REMATCH[1]}"
}

# A owns both outputs before its mutation command starts. The command remains
# gated while B attempts overlap and then completes unrelated work.
gate="${output}/gates/build"
gates+=("${gate}")
"${DEMO_BIN}" with --job build --holder alice --note 'regenerating API and types' --ttl 60 \
  generated/api.txt generated/types.txt -- bash "${HERE}/worker.sh" worker-a build "${gate}" build \
  >"${DEMO_RECEIPTS}/worker-a.stdout.txt" 2>"${DEMO_RECEIPTS}/worker-a.jsonl" &
worker=$!
children+=("${worker}")
await_ready "${gate}" "${worker}"
expect_status 1 "${DEMO_BIN}" with --job competing --holder bob --note 'updating API' generated/api.txt \
  -- bash -c 'printf "blocked mutation ran\n" >blocked-ran' \
  >"${DEMO_RECEIPTS}/worker-b.stdout.txt" 2>"${DEMO_RECEIPTS}/worker-b-refusal.jsonl"
"${DEMO_BIN}" with --job independent --holder bob --note 'writing unrelated notes' independent.txt \
  -- bash "${HERE}/worker.sh" independent independent unused independent \
  >"${DEMO_RECEIPTS}/independent.stdout.txt" 2>"${DEMO_RECEIPTS}/independent.jsonl"
"${DEMO_BIN}" show --job build >"${DEMO_RECEIPTS}/before-renewal.jsonl"
"${DEMO_BIN}" extend --job build --ttl 120 >"${DEMO_RECEIPTS}/renewal.jsonl"
"${DEMO_BIN}" show --job build >"${DEMO_RECEIPTS}/after-renewal.jsonl"
: >"${gate}"
wait "${worker}"
"${DEMO_BIN}" check generated/api.txt generated/types.txt >"${DEMO_RECEIPTS}/after-worker-a.jsonl"
printf 'Path set acquired before mutation; overlap refused; unrelated work completed; renewed acquisition released.\n'

# A later acquisition can reuse the name; the old wrapper releases only its
# own acquisition, so the replacement survives that wrapper's cleanup.
gate="${output}/gates/reused"
gates+=("${gate}")
"${DEMO_BIN}" with --job reused --holder alice reused.txt -- bash "${HERE}/worker.sh" old reused "${gate}" superseded \
  >"${DEMO_RECEIPTS}/superseded-worker.stdout.txt" 2>"${DEMO_RECEIPTS}/superseded-worker.jsonl" &
worker=$!
children+=("${worker}")
await_ready "${gate}" "${worker}"
"${DEMO_BIN}" claim --job reused --holder bob reused.txt >"${DEMO_RECEIPTS}/replacement.jsonl"
replacement_acquisition=''
acquisition_from replacement_acquisition "${DEMO_RECEIPTS}/replacement.jsonl"
: >"${gate}"
wait "${worker}"
"${DEMO_BIN}" show --job reused >"${DEMO_RECEIPTS}/replacement-survives.jsonl"
"${DEMO_BIN}" release --job reused --acquisition "${replacement_acquisition}" >"${DEMO_RECEIPTS}/replacement-release.jsonl"
printf 'Superseded cleanup preserved the replacement acquisition.\n'

# A nonzero mutation status propagates through with while it releases the
# reservation. Reservation cleanup does not roll back partial file writes.
status=0
"${DEMO_BIN}" with --job failing --holder alice failed.txt -- bash "${HERE}/worker.sh" failing failing unused failure \
  >"${DEMO_RECEIPTS}/failing-worker.stdout.txt" 2>"${DEMO_RECEIPTS}/failing-worker.jsonl" || status=$?
printf '%s\n' "${status}" >"${DEMO_RECEIPTS}/failing-worker.status"
[[ "${status}" == 17 ]]
"${DEMO_BIN}" check failed.txt >"${DEMO_RECEIPTS}/after-failure.jsonl"
printf 'Worker exit 17 propagated; its reservation was released.\n'

# Advancing only the observation's test clock shows that with neither renews
# automatically nor terminates a still-running command when the TTL expires.
gate="${output}/gates/ttl"
gates+=("${gate}")
"${DEMO_BIN}" with --job short --holder alice --ttl 1 short.txt -- bash "${HERE}/worker.sh" ttl short "${gate}" ttl \
  >"${DEMO_RECEIPTS}/ttl-worker.stdout.txt" 2>"${DEMO_RECEIPTS}/ttl-worker.jsonl" &
worker=$!
children+=("${worker}")
await_ready "${gate}" "${worker}"
GIT_LOCKS_NOW=1000002 "${DEMO_BIN}" check short.txt >"${DEMO_RECEIPTS}/expired-while-running.jsonl"
kill -0 "${worker}"
printf 'yes\n' >"${DEMO_RECEIPTS}/worker-active-after-expiry.txt"
: >"${gate}"
wait "${worker}"
printf 'TTL expired while the command remained active; automatic renewal is not provided.\n'
"${DEMO_BIN}" list >"${DEMO_RECEIPTS}/final-list.jsonl"
"${DEMO_BIN}" doctor >"${DEMO_RECEIPTS}/final-doctor.jsonl"
printf 'Artifacts and JSONL receipts: %s\n' "${output}"
