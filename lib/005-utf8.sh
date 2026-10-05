# ---------------------------------------------------------------- UTF-8 text
# LC_ALL=C makes these ranges and string offsets bytes. Exclude overlong forms,
# surrogate code points, and scalars above U+10FFFF. Bash strings cannot hold NUL.
UTF8_PATTERN=$'^([\001-\177]|[\302-\337][\200-\277]|\340[\240-\277][\200-\277]|[\341-\354\356-\357][\200-\277]{2}|\355[\200-\237][\200-\277]|\360[\220-\277][\200-\277]{2}|[\361-\363][\200-\277]{3}|\364[\200-\217][\200-\277]{2})*$'

valid_utf8() { [[ "$1" =~ ${UTF8_PATTERN} ]]; }

utf8_display() { # VAR VALUE: preserve valid scalars; replace each invalid byte for diagnostics only
  local _ud_text="$2" _ud_out='' _ud_i=0 _ud_n _ud_c _ud_part
  if valid_utf8 "${_ud_text}"; then
    printf -v "$1" '%s' "${_ud_text}"
    return 0
  fi
  while ((_ud_i < ${#_ud_text})); do
    _ud_c="${_ud_text:_ud_i:1}"
    case "${_ud_c}" in
      [$'\001'-$'\177']) _ud_n=1 ;;
      [$'\302'-$'\337']) _ud_n=2 ;;
      [$'\340'-$'\357']) _ud_n=3 ;;
      [$'\360'-$'\364']) _ud_n=4 ;;
      *) _ud_n=0 ;;
    esac
    _ud_part="${_ud_text:_ud_i:_ud_n}"
    if ((_ud_n > 0)) && valid_utf8 "${_ud_part}"; then
      _ud_out+="${_ud_part}"
      _ud_i=$((_ud_i + _ud_n))
    else
      _ud_out+=$'\357\277\275' # U+FFFD, never a surrogate or an invalid output byte
      _ud_i=$((_ud_i + 1))
    fi
  done
  printf -v "$1" '%s' "${_ud_out}"
}
