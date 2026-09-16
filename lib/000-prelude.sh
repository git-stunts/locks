#!/usr/bin/env bash
# git-locks — declare the paths you are about to write, as refs in a store.
#
#   git locks claim   --job <id> --holder <name> [--ttl <seconds>] [--parent <id>] <path>...
#   git locks batch   < records        several claims in ONE transaction, all or nothing
#   git locks release --job <id> [--record <oid> | --acquisition <id>] [--job <id>...]
#   git locks check   <path>...        exit 1 if any path is held
#   git locks list
#   git locks sweep                    delete expired locks
#   git locks store                    print the store this directory resolves to
#   git locks show    --job <id>       one lock in full, with the seconds it has left
#   git locks ttl     --job <id>       just the seconds left
#   git locks extend  --job <id> --ttl <seconds>
#   git locks with    --job <id> --holder <name> [--ttl <s>] [--wait <s>] [--sem <name>] [<path>...] -- <command>...
#   git locks sem     create|acquire|release|show|list|delete   capacity semaphores
#   git locks help | schema | version
#
# Works inside or outside a git repository: the default store is keyed on the
# repository's main git dir when there is one, else on the directory itself.
#
# Output is JSON Lines by default: one object per result on stdout, written as
# each result is known, refusals and errors as objects on stderr; every line
# conforms to schema/git-locks.schema.json, which `git locks schema` prints
# as one line. There is no plain-text mode. The one exception, stated: a command
# wrapped by `with` owns stdout; git-locks reports around it on stderr.
#
# Where the locks live: NOT in the working repository by default. The store is
# a bare repository at $GIT_LOCKS_HOME/locks/<absolute path of the subject's main repo>
# ($GIT_LOCKS_HOME defaults to ~/.git-stunts), created on first use, so a
# project's own refs stay clean. Override with GIT_LOCKS_STORE=<path> or
# GIT_LOCKS_STORE=self (the subject's own common git dir, shared by its
# worktrees), or persistently with `git config locks.store <path|self>`.
# Precedence: environment, then config, then the default.
#
# A lock is one blob (a plain-text record: job, holder, claimed, expires,
# optional parent, a family generation, and the paths) pointed at by
# refs/locks/jobs/<id> and by refs/locks/paths/<h> for every path, where <h>
# is git's own hash of the normalised path string. Every command reads the
# store once (for-each-ref plus one cat-file --batch) and compiles its intent
# into one transition per ref (create, update from an expected old value,
# delete with an expected old value, or verify), sent as a single
# `git update-ref --stdin` transaction. A stale expectation fails the whole
# transaction; commands that can re-plan do so a bounded number of times.
#
# Exit codes: 0 done (or free), 1 refused / held, 2 usage or a store error.
# GIT_LOCKS_NOW=<epoch seconds> fixes the clock (tests).
# GIT_LOCKS_PAUSE_BEFORE_COMMIT=<file> makes every transaction wait for that
# file to exist before committing; GIT_LOCKS_PAUSE_AFTER_READ=<file> makes
# every store read wait after loading; GIT_LOCKS_TRACE=<file> appends one line
# per store read. Tests force interleavings and count reads with them.
set -uo pipefail
if ((BASH_VERSINFO[0] < 4)); then
  printf 'git-locks: needs bash 4 or newer (associative arrays); this is %s\n' "${BASH_VERSION}" >&2
  exit 2
fi
export LC_ALL=C # string offsets below are byte offsets: cat-file --batch sizes are bytes

NS='refs/locks'
DEFAULT_TTL=14400
SCHEMA='git-locks/1'
SEM_SCHEMA='git-locks-sem/1'
SLOT_SCHEMA='git-locks-slot/1'
VERSION='0.6.0'
RETRIES=200   # a plan refused for a stale expectation is re-read and re-planned this many times
NOW_CACHED='' # the clock, read once per invocation by now()

usage_text() {
  cat <<'EOF'
usage: git locks claim   --job <id> --holder <name> [--ttl <seconds>] [--parent <id>] [--note <text>] <path>...
       git locks batch   < records        several claims in ONE transaction, all or nothing
       git locks release --job <id> [--record <oid> | --acquisition <id>] [--job <id>...]
       git locks check   <path>...
       git locks list
       git locks sweep
       git locks store
       git locks show    --job <id>
       git locks ttl     --job <id>
       git locks extend  --job <id> --ttl <seconds>
       git locks with    --job <id> --holder <name> [--ttl <seconds>] [--wait <seconds>] [--sem <name>] [--note <text>] [<path>...] -- <command>...
       git locks sem     create <name> --capacity <n> | acquire <name> --job <id> --holder <name> [--ttl <s>] [--wait <s>]
                                  | release <name> --job <id> [--record <oid> | --acquisition <id>] | show <name> | list | delete <name>
       git locks doctor
       git locks version
       git locks help | schema

claim    lock the paths for the job, atomically; re-claiming with the same job replaces its path set and
         its record; --parent makes it a child: the parent must be live and held by the same holder, and the
         child is released or swept with it. The claim line carries the record id of this acquisition.
         --note is one line saying why, carried on every line that names the lock: a refusal reads
         'held by alice: building the release bundle' instead of just 'held by alice'
batch    read lock records on stdin (blank-line separated: job:, holder:, ttl:, parent:, note:, paths: then
         one path per line) and claim them all in one transaction, or none
release  drop the named jobs' locks and all their descendants, in one transaction; --acquisition releases
         only if the job's current record belongs to that acquisition (an id that survives extend), --record
         only if the record oid is exactly that one
check    who holds each path, with the seconds left; exit 1 if any is held
list     every lock, live or expired, with its paths and the seconds left
sweep    delete expired locks, each with its descendants
store    print the store this directory resolves to
show     one lock in full; exit 1 if there is none
ttl      the seconds a lock has left; exit 1 if there is none
extend   move a lock's expiry to now + ttl, keeping its paths and family
with     claim, run the command, release the acquisition it made (also on failure or a signal), exit with
         the command's status; --wait retries once a second until the paths are free or the wait runs out.
         The command's stdout is its own; git-locks reports its claim and release on stderr. The lock is a
         time-bounded reservation: with does not renew it, so give --ttl the command's worst case.
sem      capacity, not exclusivity: up to <n> jobs hold a named semaphore at once; a slot expires like a
         lock; acquire is one transaction with a compare-and-swap on the semaphore's generation, so racers
         beyond capacity fail and exactly <n> win
doctor   read-only invariant check of the store: one finding line per problem, then a doctor line with the
         basis (refs and records read, the clock) and the verdict; exit 1 on findings, 2 when the store
         cannot be read (an unreadable store is never healthy). Diagnosis only: nothing is repaired
schema   print the JSON Schema every output line conforms to

output:  JSON Lines, always: one object per result on stdout, written as each result is known;
         refusals and errors are objects on stderr; help is a usage object; schema is the schema on one
         line. A command wrapped by with owns stdout.
store:   GIT_LOCKS_STORE=<path|self>, else `git config locks.store`,
         else ${GIT_LOCKS_HOME:-~/.git-stunts}/locks/<main repo path>
clock:   GIT_LOCKS_NOW=<epoch seconds> (tests)
exit:    0 done or free, 1 refused or held, 2 usage or a store error
EOF
}

usage_json() { # VAR: the usage object
  local text _j1
  text="$(usage_text)"
  json_str _j1 "${text}"
  printf -v "$1" '{"event":"usage","usage":%s}' "${_j1}"
}

usage() { # a usage error: the usage object on stderr, exit 2
  local line
  usage_json line
  printf '%s\n' "${line}" >&2
  exit 2
}

sub_usage() { # subcommand -> its usage as a usage object on stdout
  local text _j1
  text="$(sub_usage_text "$1")"
  json_str _j1 "${text}"
  printf '{"event":"usage","usage":%s}\n' "${_j1}"
}

sub_usage_text() {
  case "$1" in
    claim) printf 'usage: git locks claim --job <id> --holder <name> [--ttl <seconds>] [--parent <id>] [--note <text>] <path>...\n' ;;
    batch) printf 'usage: git locks batch < records\n' ;;
    release) printf 'usage: git locks release --job <id> [--record <oid> | --acquisition <id>] [--job <id>...]\n' ;;
    check) printf 'usage: git locks check <path>...\n' ;;
    list) printf 'usage: git locks list\n' ;;
    sweep) printf 'usage: git locks sweep\n' ;;
    store) printf 'usage: git locks store\n' ;;
    show) printf 'usage: git locks show --job <id>\n' ;;
    ttl) printf 'usage: git locks ttl --job <id>\n' ;;
    extend) printf 'usage: git locks extend --job <id> --ttl <seconds>\n' ;;
    with) printf 'usage: git locks with --job <id> --holder <name> [--ttl <seconds>] [--wait <seconds>] [--sem <name>] [--note <text>] [<path>...] -- <command>...\n' ;;
    doctor) printf 'usage: git locks doctor\n' ;;
    sem) printf 'usage: git locks sem create <name> --capacity <n> | acquire <name> --job <id> --holder <name> [--ttl <s>] [--wait <s>] | release <name> --job <id> [--record <oid> | --acquisition <id>] | show <name> | list | delete <name>\n' ;;
    *) usage_text ;;
  esac
}
