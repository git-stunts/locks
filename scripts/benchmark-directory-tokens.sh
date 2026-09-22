#!/usr/bin/env bash
# Informational benchmark. Large fixtures are synthetic loose Git objects/refs,
# calibrated against real claim/release by test/directory-token-churn.sh.
set -euo pipefail
export LC_ALL=C
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX
BENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  printf 'directory-token benchmark: %s\n' "$*" >&2
  return 2
}

fixture() { # New STORE, wide|deep|reuse, count, optional live
  local store="$1" shape="$2" count="$3" live="${4:-released}"
  [[ "${count}" =~ ^[0-9]{1,5}$ ]] || {
    fail 'count must be 0..10000'
    return 2
  }
  ((10#${count} <= 10000)) || {
    fail 'count must be 0..10000'
    return 2
  }
  count=$((10#${count}))
  [[ "${live}" == released || "${live}" == live ]] || {
    fail 'state must be released or live'
    return 2
  }
  local records="${count}"
  case "${shape}" in
    wide | reuse) ;;
    deep)
      ((count % 10 == 0)) || {
        fail 'deep count must be a multiple of 10 prefixes'
        return 2
      }
      records=$((count / 10))
      ;;
    *)
      fail 'shape must be wide, deep, or reuse'
      return 2
      ;;
  esac
  [[ ! -e "${store}" ]] || {
    fail 'refusing an existing store'
    return 2
  }
  mkdir "${store}"
  git init --bare -q "${store}"
  local inputs="${store}/fixture-inputs" i path job ancestor prefix file text
  local record_files=() prefix_files=() path_files=() record_oids=() prefix_oids=() path_oids=() prefixes=()
  local -A last_record=() prefix_seen=()
  mkdir "${inputs}"
  for ((i = 1; i <= records; i++)); do
    printf -v job 'j%05d' "${i}"
    case "${shape}" in
      wide) printf -v path 'd%05d/file.md' "${i}" ;;
      deep) printf -v path 'g%05d/a/b/c/d/e/f/g/h/i/file.md' "${i}" ;;
      reuse) printf -v path 'shared/a/b/c/d/e/f/g/h/i/file%05d.md' "${i}" ;;
      *) return 2 ;;
    esac
    file="${inputs}/record-${i}"
    printf 'schema: git-locks/1\njob: %s\nholder: benchmark\nclaimed: 1000000\nexpires: 1014400\nfamily: 0\nacquisition: fixture-%s\npaths:\n%s\n' "${job}" "${i}" "${path}" >"${file}"
    record_files+=("${file}")
    if [[ "${live}" == live ]]; then
      file="${inputs}/path-${i}"
      printf '%s' "${path}" >"${file}"
      path_files+=("${file}")
    fi
    ancestor="${path%/*}/"
    prefix=''
    while [[ -n "${ancestor}" ]]; do
      prefix+="${ancestor%%/*}/"
      ancestor="${ancestor#*/}"
      last_record["${prefix}"]=$((i - 1))
      if [[ -z "${prefix_seen[${prefix}]+x}" ]]; then
        prefix_seen["${prefix}"]=1
        prefixes+=("${prefix}")
        file="${inputs}/prefix-${#prefixes[@]}"
        printf '%s' "${prefix}" >"${file}"
        prefix_files+=("${file}")
      fi
    done
  done
  if ((records > 0)); then
    text="$(printf '%s\n' "${record_files[@]}" | git --git-dir="${store}" hash-object -w --stdin-paths)"
    mapfile -t record_oids <<<"${text}"
    text="$(printf '%s\n' "${prefix_files[@]}" | git --git-dir="${store}" hash-object --stdin-paths)"
    mapfile -t prefix_oids <<<"${text}"
    if [[ "${live}" == live ]]; then
      text="$(printf '%s\n' "${path_files[@]}" | git --git-dir="${store}" hash-object --stdin-paths)"
      mapfile -t path_oids <<<"${text}"
    fi
    {
      printf 'start\n'
      for i in "${!prefixes[@]}"; do
        printf 'create refs/locks/dirs/%s %s\n' "${prefix_oids[${i}]}" "${record_oids[${last_record[${prefixes[${i}]}]}]}"
      done
      if [[ "${live}" == live ]]; then
        for i in "${!record_oids[@]}"; do
          printf 'create refs/locks/jobs/j%05d %s\n' "$((i + 1))" "${record_oids[${i}]}"
          printf 'create refs/locks/paths/%s %s\n' "${path_oids[${i}]}" "${record_oids[${i}]}"
        done
      fi
      printf 'prepare\ncommit\n'
    } >"${inputs}/transaction"
    git --git-dir="${store}" update-ref --stdin <"${inputs}/transaction" >/dev/null
  fi
  local footprint
  footprint="$(du -sk "${store}")"
  read -r FIXTURE_WORKING_KIB _ <<<"${footprint}"
  ((FIXTURE_WORKING_KIB <= 204800)) || {
    fail 'fixture working footprint exceeded 200 MiB'
    return 1
  }
  # These files were created above in a newly created, exclusively owned store.
  rm -rf "${inputs}"
}

verify() { # STORE expected directory refs, expected live jobs/path refs
  local store="$1" want_dirs="$2" want_jobs="$3" dirs=0 jobs=0 paths=0 ref rows
  rows="$(git --git-dir="${store}" for-each-ref --format='%(refname)')" || return 1
  while IFS= read -r ref; do
    [[ -n "${ref}" ]] || continue
    case "${ref}" in
      refs/locks/dirs/*) dirs=$((dirs + 1)) ;;
      refs/locks/jobs/*) jobs=$((jobs + 1)) ;;
      refs/locks/paths/*) paths=$((paths + 1)) ;;
      *)
        fail "unexpected ref ${ref}"
        return 1
        ;;
    esac
  done <<<"${rows}"
  [[ "${dirs}:${jobs}:${paths}" == "${want_dirs}:${want_jobs}:${want_jobs}" ]] || {
    fail "wrong fixture counts: dirs=${dirs} jobs=${jobs} paths=${paths}, wanted ${want_dirs}/${want_jobs}/${want_jobs}"
    return 1
  }
  printf 'dirs=%s jobs=%s paths=%s\n' "${dirs}" "${jobs}" "${paths}"
}

ref_fingerprint() {
  git --git-dir="$1" for-each-ref --format='%(refname) %(objectname)' | git --git-dir="$1" hash-object --stdin
}

inventory() { # STORE scenario phase setup_us -> CSV, all reachable objects are blobs
  local store="$1" rows ref oid dirs=0 jobs=0 paths=0 refs=0 reachable=0 loose=0 disk key value
  local -A seen=()
  rows="$(git --git-dir="${store}" for-each-ref --format='%(refname) %(objectname)')"
  while read -r ref oid; do
    [[ -n "${ref}" ]] || continue
    refs=$((refs + 1))
    if [[ -z "${seen[${oid}]+x}" ]]; then
      seen["${oid}"]=1
      reachable=$((reachable + 1))
    fi
    case "${ref}" in
      refs/locks/dirs/*) dirs=$((dirs + 1)) ;;
      refs/locks/jobs/*) jobs=$((jobs + 1)) ;;
      refs/locks/paths/*) paths=$((paths + 1)) ;;
      *) fail "unexpected ref ${ref}" ;;
    esac
  done <<<"${rows}"
  rows="$(git --git-dir="${store}" count-objects -v)"
  while read -r key value; do [[ "${key}" != count: ]] || loose="${value}"; done <<<"${rows}"
  rows="$(du -sk "${store}")"
  read -r disk _ <<<"${rows}"
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$2" "$3" "$4" "${dirs}" "${jobs}" "${paths}" "${refs}" "${reachable}" "${loose}" "${disk}" "${5:-0}"
}

measure() { # STORE OUT SCENARIO OP REP EXPECTED_LINES command...
  local store="$1" out="$2" scenario="$3" operation="$4" repetition="$5" want_lines="$6"
  shift 6
  local stem="${out}/raw/${scenario}-${operation}-${repetition}" start end elapsed rc rss='' first rest lines=0 _line
  start="${EPOCHREALTIME/./}"
  case "${BENCH_OS}" in
    Darwin)
      if GIT_LOCKS_STORE="${store}" GIT_LOCKS_NOW=1000000 /usr/bin/time -l "${BENCH_ROOT}/bin/git-locks" "$@" >"${stem}.stdout" 2>"${stem}.metrics"; then rc=0; else rc=$?; fi
      ;;
    Linux)
      if GIT_LOCKS_STORE="${store}" GIT_LOCKS_NOW=1000000 /usr/bin/time -f 'rss_kib %M' -o "${stem}.metrics" "${BENCH_ROOT}/bin/git-locks" "$@" >"${stem}.stdout" 2>"${stem}.stderr"; then rc=0; else rc=$?; fi
      ;;
    *)
      fail 'timing currently supports Darwin or Linux'
      return 2
      ;;
  esac
  end="${EPOCHREALTIME/./}"
  elapsed=$((end - start))
  while read -r first rest; do
    if [[ "${rest}" == 'maximum resident set size' ]]; then rss="${first}"; fi
    if [[ "${first}" == rss_kib ]]; then rss=$((rest * 1024)); fi
  done <"${stem}.metrics"
  while IFS= read -r _line; do lines=$((lines + 1)); done <"${stem}.stdout"
  printf '%s,%s,%s,%s,%s,%s,%s\n' "${scenario}" "${operation}" "${repetition}" "${elapsed}" "${rss}" "${rc}" "${lines}" >>"${out}/observations.csv"
  if [[ ! "${rss}" =~ ^[0-9]+$ ]] || ((elapsed < 0 || rc != 0 || lines != want_lines)); then
    fail "invalid observation ${scenario}/${operation}/${repetition}; raw failure retained in ${stem}.*"
    return 1
  fi
  rm "${stem}.stdout" # Successful payloads were checked; failures are retained.
}

summarize() { # OUT: sorted per-operation distributions, no timing gate
  local out="$1" scenario operation repetition elapsed rss rc lines key values n
  local -A groups=()
  while IFS=, read -r scenario operation repetition elapsed rss rc lines; do
    [[ "${scenario}" != scenario ]] || continue
    key="${scenario},${operation}"
    groups["${key}"]+="${elapsed}"$'\n'
  done <"${out}/observations.csv"
  printf 'scenario,operation,repetitions,min_us,median_us,max_us\n' >"${out}/summary.csv"
  for key in "${!groups[@]}"; do
    values="$(printf '%s' "${groups[${key}]}" | sort -n)"
    local sorted=()
    mapfile -t sorted <<<"${values}"
    n="${#sorted[@]}"
    printf '%s,%s,%s,%s,%s\n' "${key}" "${n}" "${sorted[0]}" "${sorted[$((n / 2))]}" "${sorted[$((n - 1))]}"
  done | sort >>"${out}/summary.csv"
}

run_matrix() { # NEW OUTPUT DIRECTORY [quick]
  local out="$1" mode="${2:-full}" scratch started setup_us scenario shape count state dirs jobs repetitions=3 entry operation rep expected before after probe_hash probe_oid current
  ((BASH_VERSINFO[0] >= 5)) || {
    fail 'timing requires Bash 5 for EPOCHREALTIME'
    return 2
  }
  [[ "${mode}" == full || "${mode}" == quick ]] || {
    fail 'mode must be full or quick'
    return 2
  }
  [[ ! -e "${out}" ]] || {
    fail 'refusing an existing output directory'
    return 2
  }
  mkdir -p "${out}/raw"
  out="$(cd "${out}" && pwd)"
  scratch="$(mktemp -d "${TMPDIR:-/tmp}/locks-churn-matrix.XXXXXX")"
  BENCH_OS="$(uname -s)"
  local matrix=('empty:wide:0:released' 'wide-1000:wide:1000:released' 'wide-10000:wide:10000:released' 'deep-1000:deep:1000:released' 'deep-10000:deep:10000:released' 'reuse-1000:reuse:1000:released' 'reuse-10000:reuse:10000:released' 'live-1000:wide:1000:live' 'empty-after:wide:0:released')
  if [[ "${mode}" == quick ]]; then
    repetitions=1
    matrix=('empty:wide:0:released' 'wide-3:wide:3:released' 'deep-20:deep:20:released' 'reuse-5:reuse:5:released' 'live-3:wide:3:live')
  fi
  local revision binary_blob generator_blob stamp
  revision="$(git -C "${BENCH_ROOT}" rev-parse HEAD)"
  binary_blob="$(git -C "${BENCH_ROOT}" hash-object bin/git-locks)"
  generator_blob="$(git -C "${BENCH_ROOT}" hash-object scripts/benchmark-directory-tokens.sh)"
  stamp="$(date -u +%FT%TZ)"
  {
    printf 'specimen_revision=%s\n' "${revision}"
    printf 'binary_git_blob=%s\n' "${binary_blob}"
    printf 'generator_git_blob=%s\n' "${generator_blob}"
    printf 'bash=%s\nmode=%s\nrepetitions=%s\n' "${BASH_VERSION}" "${mode}" "${repetitions}"
    git --version
    uname -srm
    printf 'started_utc=%s\n' "${stamp}"
    printf 'scratch=%s\n' "${scratch}"
    printf 'Synthetic loose-object/ref fixtures; acquisition ids deterministic. Setup, inventory and cleanup excluded from timing. Filesystem caches not cleared. elapsed_us uses Bash EPOCHREALTIME around native time plus the CLI; max RSS is the native per-command resource report, not aggregate concurrent memory.\n'
  } >"${out}/environment.txt"
  printf 'scenario,operation,repetition,elapsed_us,max_rss_bytes,exit_code,stdout_lines\n' >"${out}/observations.csv"
  printf 'scenario,phase,setup_us,dirs,jobs,paths,refs,reachable_blobs,loose_objects,disk_kib,setup_working_kib\n' >"${out}/fixtures.csv"
  for entry in "${matrix[@]}"; do
    IFS=: read -r scenario shape count state <<<"${entry}"
    local store="${scratch}/${scenario}.git"
    started="${EPOCHREALTIME/./}"
    fixture "${store}" "${shape}" "${count}" "${state}"
    setup_us=$((${EPOCHREALTIME/./} - started))
    dirs="${count}"
    jobs=0
    [[ "${shape}" != reuse ]] || dirs=10
    [[ "${state}" != live ]] || jobs="${count}"
    verify "${store}" "${dirs}" "${jobs}" >/dev/null
    inventory "${store}" "${scenario}" before "${setup_us}" "${FIXTURE_WORKING_KIB}" >>"${out}/fixtures.csv"
    before="$(ref_fingerprint "${store}")"
    probe_hash="$(printf '_benchmark_probe/' | git --git-dir="${store}" hash-object --stdin)"
    for operation in check exact_claim prefix_claim list doctor; do
      for ((rep = 1; rep <= repetitions; rep++)); do
        local args=()
        expected=1
        case "${operation}" in
          check) args=(check _benchmark_probe.md) ;;
          exact_claim) args=(claim --job benchmark-probe --holder benchmark _benchmark_probe.md) ;;
          prefix_claim) args=(claim --job benchmark-probe --holder benchmark _benchmark_probe/) ;;
          list)
            args=(list)
            expected="${jobs}"
            ;;
          doctor) args=(doctor) ;;
          *) return 2 ;;
        esac
        measure "${store}" "${out}" "${scenario}" "${operation}" "${rep}" "${expected}" "${args[@]}"
        if [[ "${operation}" == *_claim ]]; then
          probe_oid="$(git --git-dir="${store}" rev-parse refs/locks/jobs/benchmark-probe)"
          GIT_LOCKS_STORE="${store}" GIT_LOCKS_NOW=1000000 "${BENCH_ROOT}/bin/git-locks" release --job benchmark-probe >/dev/null
          if [[ "${operation}" == prefix_claim ]]; then
            current="$(git --git-dir="${store}" rev-parse "refs/locks/dirs/${probe_hash}")"
            [[ "${current}" == "${probe_oid}" ]] || {
              fail 'probe token changed unexpectedly'
              return 1
            }
            git --git-dir="${store}" update-ref -d "refs/locks/dirs/${probe_hash}" "${probe_oid}"
          fi
        fi
        after="$(ref_fingerprint "${store}")"
        [[ "${before}" == "${after}" ]] || {
          fail "fixture drift after ${scenario}/${operation}"
          return 1
        }
      done
    done
    verify "${store}" "${dirs}" "${jobs}" >/dev/null
    inventory "${store}" "${scenario}" after 0 >>"${out}/fixtures.csv"
    printf 'measured %s\n' "${scenario}"
    # The matrix created this store under its private mktemp directory.
    rm -rf "${store}"
  done
  rmdir "${scratch}"
  summarize "${out}"
  stamp="$(date -u +%FT%TZ)"
  printf 'completed_utc=%s\n' "${stamp}" >>"${out}/environment.txt"
}

main() {
  case "${1:-}" in
    fixture)
      (($# == 4 || $# == 5)) || {
        fail 'fixture STORE SHAPE COUNT [live]'
        return 2
      }
      fixture "$2" "$3" "$4" "${5:-released}"
      ;;
    verify)
      (($# == 4)) || {
        fail 'verify STORE DIRS JOBS'
        return 2
      }
      verify "$2" "$3" "$4"
      ;;
    run)
      (($# == 2 || $# == 3)) || {
        fail 'run OUTDIR [quick]'
        return 2
      }
      run_matrix "$2" "${3:-full}"
      ;;
    *)
      fail 'usage: benchmark-directory-tokens.sh fixture|verify|run'
      return 2
      ;;
  esac
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
