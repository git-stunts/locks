---
title: "git-locks: cooperative path reservations"
date: 2026-09-15
author: James Ross
description: "Advisory path locks for cooperative workers on one machine. Bash and Git, with JSON Lines output."
tags: [git, locking, bash, concurrency, jsonl]
draft: false
status: published
project: git-stunts/locks
version: 0.7.0
---
```
     ▄▄▄▄▄▄▄    ▄▄▄▄▄▄    ▄▄▄▄▄▄▄▄▄▄         ▄▄▄▄▄▄            ▄▄▄▄▄▄           ▄▄▄▄▄▄ ▄▄▄▄▄▄   ▄▄▄▄▄▄      ▄▄▄▄▄▄▄▄▄▄
  ▄██▀▀  ▀▀▀     ▓██▓  ▄░▄▀  ▓██▄  ▀▄░▄       ▒ ░▓          ▄██▀▀  ▀▀░▓▄     ▄██▀▀  ▀▀  ▓██▓     ▓██▓    ▄░▓░▀   ▓░█▓ 
 ░██▌            ▒█░▒        ▒██▓             ░█░▓         ░██▌      ▐░░▒   ░██▌        ▒█░▒    ▐▒█░▒   ▒░░▒          
▒██░  ▄▄▄▄▄▄▄▄▄  ▒ ░░        ▒██▓             ░ ░▓        ▒██░        ▒█░▒ ▒██░         ▒ ░░▄▄▄▀██ ▀     ▀▀░░▄▄▄▄     
▓█░░      ▓██▓   ▒██░        ▒██▒             ▒█░▓        ▓█░░        ▓██▒ ▓█░░         ▒██░   ▀▄███▄          ▀░██▄  
▓█░▒      ▒█░▓   ▒█░░        ▒██░             ▓██▓        ▓█░▒        ▓██░ ▓█░▒         ▒█░░     ▒█░░   ▒█░░     ▒█░░ 
 ▓▒▒▌     ███▓   ▓█░▒        ▓██▒             ▓██░      ▒  ▓▒▒▌      ▐░██   ▓▒▒▌        ▓█░▒     ▓█░▒   ▓█░▒    ▐██░▒ 
  ▀░▒▄▄  ▄███▓   ▓█░▓        ▓██▓             ▒██░▄▄▄▄▄░░   ▀░▒▄▄  ▄█░█▀     ▀░▒▄▄  ▄█  ▓█░▓     ▓█░▓   ▓█░▓   ▄███░▀ 
     ▀▀▀▀ ▀▀▀▀  ▀▀▀▀▀▀      ▀▀▀▀▀▀           ▀▀▀▀▀▀▀▀▀▀▀▀      ▀▀▀▀▀▀           ▀▀▀▀▀▀ ▀▀▀▀▀▀   ▀▀▀▀▀▀ ▀▀▀▀▀▀▀▀▀▀▀    
```

# git-locks

Reserve paths before parallel workers change them. A refusal identifies the holder, job, and reason for the existing reservation.

Bash and Git provide the store. No daemon is required. **Locks are advisory:** every worker must acquire a lock and obey its expiry.

## Install

Requirements: **Bash 4+**, **Git 2.31+**, and `ps` with `pgid` and `tpgid` support (Linux and macOS).
On macOS, put a newer Bash on `PATH`; `/bin/bash` 3.2 is insufficient.

From a release or reviewed checkout:

```sh
make install                   # copies the script to ~/.local/bin
export PATH="$HOME/.local/bin:$PATH"
git locks version
```

Use `make install PREFIX=/your/prefix` for another location.
Installation copies a snapshot. Repeat the command to upgrade.

## Quick start

Run this example from your project's root:

```sh
git locks with --job "report-$$" --holder "${USER:-worker}" \
  --note 'update the report' --ttl 60 --wait 10 report.md -- \
  sh -c 'printf "%s\n" "Ready" > report.md'

git locks list
git locks doctor
```

`with` acquires the paths, starts the command, and attempts release after it exits.
A trailing `/` reserves a directory prefix.
`--wait 10` waits up to ten seconds for the locks.
Without `--wait`, a conflict returns immediately.

**TTL is the reservation lifetime, in seconds.** `with` does not renew automatically or stop the command at expiry.
Keep work within its TTL, or use [guarded renewal](docs/time.md#renewal).
`check` only reports state; it does not grant a lock.

Workers must use the same store and path names.
Linked worktrees share the default store, separate from project refs.
For different repositories to share a resource, select the same explicit [store](docs/store-initialization.md).

## When to use

- Cooperative agents, scripts, and build workers on one machine.
- Several paths that must be acquired together, or directory prefixes.
- Visible ownership and refusal reasons, with JSON Lines output for tools.
- A shared concurrency limit through a [semaphore](docs/usage.md#semaphores).

## When not to use

| Need | Use instead |
| --- | --- |
| One simple local command lock | [util-linux `flock`](https://man7.org/linux/man-pages/man1/flock.1.html), where available. |
| Coordination across machines | A service such as [etcd](https://etcd.io/docs/v3.6/dev-guide/api_concurrency_reference_v3/). The protected resource must reject writes from expired owners when required. |
| Protection against workers that ignore locks | OS permissions or a sandbox. git-locks cannot prevent their writes. |
| Enforced CPU, memory, or disk limits | OS/container limits and filesystem quotas. For example, [Docker CPU and memory limits](https://docs.docker.com/engine/containers/resource_constraints/). Semaphores only count admissions. |

All writers contend on one Git ref. Store scans grow with stored state.
Measure your workload before use at high volume.
Tests cover specified cases; they do not prove correctness for every possible execution.

## How it works

```mermaid
flowchart LR
    W["Workers"] -->|"read and conditionally update"| R["refs/locks/state"]
    R --> T["Immutable Git tree"]
    T --> B["Lock records"]
```

One ref selects the complete lock state.
See the [Git object layout and two-worker example](docs/state-protocol.md) for the publication rules.

## Documentation

- [Roadmap and executable task plans](ROADMAP.md)

- [Commands, paths, output, and examples](docs/usage.md)
- [Wrapper lifetime and failure handling](docs/wrapper-lifetime.md)
- [Store setup](docs/store-initialization.md), [trust](docs/store-trust.md), and [recovery](docs/state-integrity.md)
- [State protocol and offline upgrade](docs/state-protocol.md)
- [Development and releases](docs/development.md), [test isolation](docs/testing.md), and [changelog](CHANGELOG.md)

## License

[Apache 2.0](LICENSE). See [NOTICE](NOTICE).
