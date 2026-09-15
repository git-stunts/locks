# git-locks

Declare the paths you are about to write, as git refs. Pure bash and git. No daemon, no lock files in the worktree, no refs in your project by default, nothing to install but one script on your `PATH`.

```sh
git locks claim   --job 2026-09-15-report --holder alice notes/report.md data/q3.csv
git locks check   notes/report.md          # exit 1 while held, and says by whom
git locks list                             # everything, with seconds left
git locks show    --job 2026-09-15-report  # one lock in full
git locks ttl     --job 2026-09-15-report  # just the seconds left
git locks extend  --job 2026-09-15-report --ttl 7200
git locks release --job 2026-09-15-report
git locks sweep                            # drop expired locks

# claim, run, release — also on failure or Ctrl-C; exits with the command's status
git locks with --job build --holder alice --wait 30 dist/ -- make release

# a child lives and dies with its parent: releasing or sweeping `build` takes `build-docs` too
git locks claim --job build-docs --parent build --holder alice docs/

# several locks in ONE transaction, all or nothing; several releases likewise
git locks batch < locks.txt
git locks release --job build --job other
```

Works inside a git repository or in any plain directory.

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

Not in your repository, by default. The store is a bare repository at `~/.git-stunts/locks/<absolute path of the main repo>`, created on first use, so `refs/locks/` never appears in your project and linked worktrees of one repo share one store. Outside any git repository the store is keyed on the directory itself, so the tool works in a plain folder too (`self` is the one mode that needs a repository). Configurable, in this order:

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

A child lock records `parent: <job>`. Its claim carries a `verify` on the parent's ref inside the same transaction, so the parent cannot vanish between the check and the commit. Releasing or sweeping a lock takes every descendant with it, in one transaction: a child never outlives its parent, and a parent's expiry is the family's. Expiry itself is not inherited; `extend` a parent to keep a family alive.

## Commands

Every command takes `--text` first for the human form. Default output is JSON Lines.

| Command | Does | Stdout line(s) | Exit |
|---|---|---|---|
| `claim --job <id> --holder <name> [--ttl <s>] <path>...` | atomically lock the paths for the job; re-claiming with the same job replaces its path set | one `claimed` object; refusals on stderr | 0 claimed, 1 refused, 2 usage |
| `check <path>...` | who holds each path, in argument order | one object per path as it is examined | 0 all free, 1 any held |
| `list` | every lock, live or expired, with its paths | one object per lock; nothing when empty | 0 |
| `sweep` | delete expired locks | one `swept` object per lock, as it goes | 0 |
| `store` | the resolved store path | one `store` object | 0 |
| `show --job <id>` | one lock in full, with `remaining` seconds | one object, same shape as a `list` line | 0, 1 if no such lock |
| `ttl --job <id>` | the seconds a lock has left | one `{job, expires, remaining}` object | 0, 1 if no such lock |
| `extend --job <id> --ttl <s>` | move the expiry to now + ttl, paths unchanged, atomically | one `extended` object | 0, 1 if no such lock |
| `claim … --parent <id>` | make the lock a child: the parent must be live and held by the same holder (verified inside the transaction); the child is released or swept with it | as `claim`, with `parent` | 0, 1 if refused |
| `batch < records` | claim several locks in one transaction, or none; records are blank-line separated `job:`, `holder:`, `ttl:`, `parent:`, then `paths:` with one path per line | one `claimed` object per record | 0, 1 if any is refused, 2 on a malformed record |
| `release --job <id> [--job <id>...]` | release several jobs and all their descendants in one transaction | one object per job, `cascaded` lists the descendants | 0 |
| `with --job <id> --holder <name> [--ttl <s>] [--wait <s>] [--parent <id>] <path>... -- <cmd>...` | claim, run the command, release; `--wait` retries once a second until the paths are free or the wait runs out | the command's own stdout; git-locks' `claimed`, `released` and refusals go to **stderr** | the command's exit status; 1 if never acquired; 130/143 on INT/TERM after releasing |
| `version` | tool name and version | one object | 0 |
| `schema` | the JSON Schema every line above conforms to | the schema document | 0 |
| `help`, `--help`, `<cmd> --help` | usage | text | 0 |

## Output schema

Every JSON line git-locks writes, on stdout or stderr, matches exactly one definition in [`schema/git-locks.schema.json`](schema/git-locks.schema.json) (JSON Schema 2020-12). `git locks schema` prints that document byte-for-byte, and the test suite validates every line it provokes against it, so the contract cannot drift from the code. Consumers can pin the `$id` URL or the file at a tagged commit.

Paths are repo-relative, `./` prefixes are stripped, and absolute or `..` paths are refused. A path may contain spaces; it may not contain a newline. Job ids match `[A-Za-z0-9][A-Za-z0-9._-]*`.

`GIT_LOCKS_NOW=<epoch seconds>` fixes the clock, for tests. Timestamps in JSON are epoch seconds; the `--text` form prints ISO-8601 UTC.

## Versioning and releases

`VERSION` in `bin/git-locks` is the version. A push to `main` whose version has no tag yet gets an annotated tag `v<version>` and a GitHub release whose notes are that version's section of `CHANGELOG.md`, with the script and the schema attached, from the `release` job in `.github/workflows/ci.yml`. So a release is: bump `VERSION`, write the changelog section, merge.

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
