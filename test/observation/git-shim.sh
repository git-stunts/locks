#!/usr/bin/env bash
# Inject exactly one synthetic ref observation; retries use real Git reads.
# Objects and update-ref transactions always use real Git in the isolated store.
set -euo pipefail
OBS_CASE="${OBS_CASE:?set the isolated case directory}"
OBS_INJECT_READ="${OBS_INJECT_READ:?set the read ordinal}"
OBS_REAL_GIT="${OBS_REAL_GIT:?set the real Git executable}"
for arg in "$@"; do
  if [[ "${arg}" == for-each-ref ]]; then
    read_number=0
    [[ ! -f "${OBS_CASE}/read-count" ]] || read -r read_number <"${OBS_CASE}/read-count"
    read_number=$((read_number + 1))
    printf '%s\n' "${read_number}" >"${OBS_CASE}/read-count"
    if [[ "${read_number}" == "${OBS_INJECT_READ}" ]]; then
      : >"${OBS_CASE}/injected"
      cat "${OBS_CASE}/observed.refs"
      printf 'injected\n' >>"${OBS_CASE}/reads.log"
      exit 0
    fi
    printf 'real\n' >>"${OBS_CASE}/reads.log"
  elif [[ "${arg}" == update-ref ]]; then
    n=0
    [[ ! -f "${OBS_CASE}/transaction-count" ]] || read -r n <"${OBS_CASE}/transaction-count"
    n=$((n + 1))
    printf '%s\n' "${n}" >"${OBS_CASE}/transaction-count"
    cat >"${OBS_CASE}/transaction-${n}.stdin"
    "${OBS_REAL_GIT}" "$@" <"${OBS_CASE}/transaction-${n}.stdin"
    exit "$?"
  fi
done
exec "${OBS_REAL_GIT}" "$@"
