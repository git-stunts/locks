# git-locks

Declare the paths you are about to write, as git refs. Pure bash and git. No daemon, no lock files in the worktree, no refs in your project by default, nothing to install but one script on your `PATH`.

```sh
git locks claim   --job 2026-09-15-report --holder alice notes/report.md data/q3.csv
git locks check   notes/report.md          # exit 1 while held, and says by whom
git locks list
git locks release --job 2026-09-15-report
git locks sweep                            # drop expired locks
```

Output is JSON Lines by default, one object per result, written as each result is known:

```text
$ git locks check notes/report.md data/other.csv
{"path":"notes/report.md","state":"held","holder":"alice","job":"2026-09-15-report","expires":1757986889}
{"path":"data/other.csv","state":"free"}
```

A claim that overlaps a live lock is refused with exit 1, one line per held path on stderr, naming the holder:

```text
{"event":"refused","path":"notes/report.md","holder":"alice","job":"2026-09-15-report","expires":1757986889}
```

`--text` before the subcommand switches every command to human-readable lines:

```text
$ git locks --text check notes/report.md
notes/report.md: held by alice (job 2026-09-15-report, until 2026-09-15T21:41:29Z)
```

## Why

Two writers on one working copy refuse each other on untracked files, and the only fix is a message one of them forgets to send. A lock that names its holder turns the refusal into the message. Storing it in git means it is inspectable with git alone, survives a shell dying, cannot show up as an untracked path, and is atomic for free.

## Where the locks live

Not in your repository, by default. The store is a bare repository at `~/.git-stunts/locks/<absolute path of the main repo>`, created on first use, so `refs/locks/` never appears in your project and linked worktrees of one repo share one store. Configurable, in this order:

| Setting | Effect |
|---|---|
| `GIT_LOCKS_STORE=<path>` | use that directory as the store (created bare if missing) |
| `GIT_LOCKS_STORE=self` | keep the refs in the repository's own common git dir |
| `git config locks.store <path\|self>` | the same, persistently, per repository |
| `GIT_LOCKS_HOME=<dir>` | relocate the default root from `~/.git-stunts` |

`git locks store` prints whatever resolved.

## How it works

One lock is one blob, a plain-text record:

```text
schema: git-locks/1
job: 2026-09-15-report
holder: alice
claimed: 1757972489
expires: 1757986889
paths:
data/q3.csv
notes/report.md
```

In the store it is pointed at by `refs/locks/jobs/<job>` and by `refs/locks/paths/<h>` for every path, where `<h>` is `git hash-object` of the path string. A claim is one `git update-ref --stdin` transaction: `create` for every free path, `update` with the expected old value for a path the same job already holds or for an expired lock in the way, and the job ref alongside. The transaction is all-or-nothing, so a claim with one held path among several takes nothing, and twenty racing claimants on one path produce exactly one winner. That race is a test, not a promise.

Expiry is a timestamp in the record, four hours by default (`--ttl` in seconds). An expired lock is reported as expired, is free to claim over, and is evicted whole when that happens. `sweep` removes expired locks on demand.

## Commands

Every command takes `--text` first for the human form. Default output is JSON Lines.

| Command | Does | Stdout line(s) | Exit |
|---|---|---|---|
| `claim --job <id> --holder <name> [--ttl <s>] <path>...` | atomically lock the paths for the job; re-claiming with the same job replaces its path set | one `claimed` object; refusals on stderr | 0 claimed, 1 refused, 2 usage |
| `release --job <id>` | drop the job's lock and every path ref that still points at it | one `released` or `nothing` object | 0 |
| `check <path>...` | who holds each path, in argument order | one object per path as it is examined | 0 all free, 1 any held |
| `list` | every lock, live or expired, with its paths | one object per lock; nothing when empty | 0 |
| `sweep` | delete expired locks | one `swept` object per lock, as it goes | 0 |
| `store` | the resolved store path | one `store` object | 0 |
| `version` | tool name and version | one object | 0 |
| `schema` | the JSON Schema every line above conforms to | the schema document | 0 |
| `help`, `--help`, `<cmd> --help` | usage | text | 0 |

## Output schema

Every JSON line git-locks writes, on stdout or stderr, matches exactly one definition in [`schema/git-locks.schema.json`](schema/git-locks.schema.json) (JSON Schema 2020-12). `git locks schema` prints that document byte-for-byte, and the test suite validates every line it provokes against it, so the contract cannot drift from the code. Consumers can pin the `$id` URL or the file at a tagged commit.

Paths are repo-relative, `./` prefixes are stripped, and absolute or `..` paths are refused. A path may contain spaces; it may not contain a newline. Job ids match `[A-Za-z0-9][A-Za-z0-9._-]*`.

`GIT_LOCKS_NOW=<epoch seconds>` fixes the clock, for tests. Timestamps in JSON are epoch seconds; the `--text` form prints ISO-8601 UTC.

## Install

```sh
make install            # symlinks bin/git-locks into ~/.local/bin
git locks list          # git dispatches `git locks` to git-locks on PATH
```

## Develop

```sh
make lint               # shellcheck with every optional check on, shfmt
make test               # test/test.sh, pure bash, temporary repositories; needs python3 with jsonschema for the schema checks
git config --local core.hooksPath scripts/hooks   # pre-commit lints, pre-push tests
```

## Limits, stated

- The lock is advisory. Nothing stops a writer that never claimed. The consumer that lands writes (a commit script, a CI step) is where refusal belongs; `check` exits 1 for exactly that use.
- One machine. The store is local; a shared remote would need a fetch before every claim and is out of scope.
- `git rev-parse --path-format=absolute` and `update-ref --stdin` transactions need git 2.31 or newer.
- The claim reads current refs, then runs the transaction. A racer can win in between; the transaction then fails and the loser is told who won. That is the designed outcome, not a gap.

## License

Apache 2.0. See `LICENSE` and `NOTICE`.
