# ---------------------------------------------------------------- record validation
# Validate the authority attached to a ref, not every blob: directory and
# semaphore generation tokens are opaque. Doctor uses the same decoder but
# reports findings instead of refusing the snapshot.

record_uint() { # VAR text: decimal in the nonnegative signed 64-bit range
  [[ "$2" =~ ^[0-9]+$ ]] || return 1
  local digits="$2" limit=9223372036854775808
  while [[ "${digits}" == 0?* ]]; do digits="${digits#0}"; done
  ((${#digits} < 19)) || {
    ((${#digits} == 19)) && [[ "x${digits}" < "x${limit}" ]] || return 1
  }
  printf -v "$1" '%s' "${digits}"
}

RECORD_ERROR=''
record_invalid() {
  RECORD_ERROR="$1"
  return 1
}

validate_record() { # oid lock|meta|slot: parsed values are safe before arithmetic
  local oid="$1" role="$2" schema key value numbers paths p
  parse_record "${oid}"
  RECORD_ERROR="${R_INVALID[${oid}]:-}"
  [[ -z "${RECORD_ERROR}" ]] || return 1
  case "${role}" in
    lock)
      schema="${SCHEMA}"
      numbers='claimed expires family'
      ;;
    meta)
      schema="${SEM_SCHEMA}"
      numbers='capacity created'
      ;;
    slot)
      schema="${SLOT_SCHEMA}"
      numbers='claimed expires'
      ;;
    *)
      record_invalid 'unknown record role'
      return 1
      ;;
  esac
  [[ "${R_FIELD["${oid} schema"]:-}" == "${schema}" ]] || {
    record_invalid "expected schema ${schema}"
    return 1
  }
  for key in ${numbers}; do
    value="${R_FIELD["${oid} ${key}"]:-}"
    # Older lock records may omit family; no membership changes means zero.
    [[ "${role}" == lock && "${key}" == family && -z "${R_FIELD["${oid} family"]+x}" ]] && value=0
    record_uint value "${value}" || {
      record_invalid "invalid ${key}"
      return 1
    }
    [[ "${key}" != capacity || "${value}" != 0 ]] || {
      record_invalid 'capacity must be positive'
      return 1
    }
    R_FIELD["${oid} ${key}"]="${value}"
  done
  if [[ "${role}" != lock ]]; then
    valid_job "${R_FIELD["${oid} semaphore"]:-}" || {
      record_invalid 'invalid semaphore'
      return 1
    }
  fi
  if [[ "${role}" != meta ]]; then
    valid_job "${R_FIELD["${oid} job"]:-}" || {
      record_invalid 'invalid job'
      return 1
    }
    valid_holder "${R_FIELD["${oid} holder"]:-}" || {
      record_invalid 'invalid holder'
      return 1
    }
    valid_holder "${R_FIELD["${oid} acquisition"]:-}" || {
      record_invalid 'invalid acquisition'
      return 1
    }
  fi
  if [[ "${role}" == lock ]]; then
    value="${R_FIELD["${oid} parent"]:-}"
    [[ -z "${value}" ]] || valid_job "${value}" || {
      record_invalid 'invalid parent'
      return 1
    }
    valid_note "${R_FIELD["${oid} note"]:-}" || {
      record_invalid 'invalid note'
      return 1
    }
    paths="${R_PATHS[${oid}]:-}"
    [[ -n "${paths}" ]] || {
      record_invalid 'no paths'
      return 1
    }
    while IFS= read -r p; do
      # Stored paths must already be lexical keys; do not glob or normalize
      # them against the reader's working directory.
      case "/${p}/" in
        //* | *//*/* | */./* | */../*)
          record_invalid 'invalid stored path'
          return 1
          ;;
        *) ;;
      esac
      [[ -n "${p}" ]] || {
        record_invalid 'empty stored path'
        return 1
      }
    done <<<"${paths}"
  elif [[ -n "${R_PATHS[${oid}]:-}" ]]; then
    record_invalid 'unexpected paths'
    return 1
  fi
  return 0
}

validate_snapshot() {
  local ref oid role rest name job
  local -A checked=()
  for ref in "${!REF_OID[@]}"; do
    oid="${REF_OID[${ref}]}"
    case "${ref}" in
      "${NS}"/jobs/* | "${NS}"/paths/*) role=lock ;;
      "${NS}"/sem/*/meta) role=meta ;;
      "${NS}"/sem/*/slots/*) role=slot ;;
      *) continue ;;
    esac
    if [[ -z "${checked["${oid} ${role}"]+x}" ]]; then
      validate_record "${oid}" "${role}" || store_error "${ref}: record ${oid}: ${RECORD_ERROR}"
      checked["${oid} ${role}"]=1
    fi
    case "${ref}" in
      "${NS}"/jobs/*)
        [[ "${R_FIELD["${oid} job"]}" == "${ref#"${NS}"/jobs/}" ]] || store_error "${ref}: record names a different job"
        ;;
      "${NS}"/sem/*)
        rest="${ref#"${NS}"/sem/}"
        name="${rest%%/*}"
        [[ "${R_FIELD["${oid} semaphore"]}" == "${name}" ]] || store_error "${ref}: record names a different semaphore"
        if [[ "${role}" == slot ]]; then
          job="${rest#*/slots/}"
          [[ "${R_FIELD["${oid} job"]}" == "${job}" ]] || store_error "${ref}: record names a different job"
        fi
        ;;
      *) ;;
    esac
  done
}
