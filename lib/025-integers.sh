# ------------------------------------------------------------ bounded integers

INTEGER_MAX=9223372036854775807

decimal_uint() { # VAR text: canonical decimal in the nonnegative signed 64-bit range
  [[ "$2" =~ ^[0-9]+$ ]] || return 1
  local _du_digits="$2" _du_limit=9223372036854775808
  _du_digits="${_du_digits#"${_du_digits%%[!0]*}"}"
  _du_digits="${_du_digits:-0}"
  ((${#_du_digits} < 19)) || {
    ((${#_du_digits} == 19)) && [[ "x${_du_digits}" < "x${_du_limit}" ]] || return 1
  }
  printf -v "$1" '%s' "${_du_digits}"
}

time_sum_v() { # VAR canonical-base canonical-duration: check before addition
  (($3 <= INTEGER_MAX - $2)) || return 1
  printf -v "$1" '%s' "$(($2 + $3))"
}

expiry_v() { # VAR canonical-now canonical-ttl: fail before writing an invalid record
  time_sum_v "$1" "$2" "$3" || fail "--ttl exceeds the available expiry range ($((INTEGER_MAX - $2)) seconds at this clock)" 2
}
