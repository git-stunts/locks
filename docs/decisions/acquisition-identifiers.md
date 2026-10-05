---
schema: "git-locks-decision/1"
id: "acquisition-identifiers"
status: "proposed"
task: "GL-006"
issue: "https://github.com/git-stunts/locks/issues/74"
created: "2026-10-05"
baseline_commit: "6735e52007ab86a37feda8b43b1d43742fdb5f94"
---

# Acquisition identifiers

## Proposed decision

Keep acquisition identifiers opaque. An identifier must be a nonempty UTF-8 line without carriage return, line feed, or NUL.
Compare the complete identifier without normalization. Do not require the current generator's numeric pattern.

An acquisition identifies one reservation lifetime. A record object ID identifies one stored version of that reservation.
Renewal can change the record object ID while the acquisition stays the same.
Callers must retain the returned acquisition value and pass it unchanged when they need an ownership guard.

This proposal awaits the task's review and recorded acceptance. It does not complete issue #74 or GL-007.

## Why

The current public validators accept opaque identifiers. Stored lock and semaphore records use the same text rule.
Offline migration preserves existing record objects. It does not replace acquisition identifiers with newly generated values.
A new generator-pattern restriction could reject a store that the current validator accepts.
No migration rule or user requirement justifies that compatibility change.

The current generator combines time, process ID, and random values. That format describes its implementation, not the caller's validation contract.
A syntactically valid value can still be stale. Pattern validation cannot establish ownership.

These values are not passwords, authenticated principals, or fencing tokens. The tool coordinates cooperating callers with access to one authority.
This decision does not claim cryptographic randomness, collision impossibility, or protection from a writer that ignores the protocol.

## Required behavior

| Input or state | Required result |
| --- | --- |
| Supplied empty identifier, invalid UTF-8, carriage return, or line feed | Usage error; exit 2; no mutation. |
| NUL in a stored record | Reject the record through the byte-validating decoder. Process arguments cannot contain NUL. |
| Valid identifier that differs from an existing reservation | Release reports `nothing` with `superseded`, exit 0. Renewal refuses with `superseded`, exit 1. |
| Valid guard for an absent job or slot | Preserve the command's existing absence result. Absence does not establish that the guard was once valid. |
| Matching acquisition guard | Continue the command's other checks. A match alone does not permit an expired renewal. |
| Both `--record` and `--acquisition` supplied | Require each value to match its own field. Option order must not remove a guard. |
| Guard omitted | Preserve the documented unguarded operation. Do not imply that it proves caller ownership. |
| Invalid acquisition in stored authority | Ordinary operations fail closed. Doctor reports the invalid record. |

“Unknown” means a well-formed value that does not match the current acquisition. It is not a separate syntax error.
For example, `stale-owner` is well formed. It cannot release a reservation whose acquisition differs.

Path re-claim creates a new acquisition. Path renewal preserves the acquisition.
A live semaphore refresh by its holder preserves the acquisition. Re-acquisition after expiry creates a new one.
Family record changes preserve the parent's acquisition. A record guard can therefore become stale while its acquisition guard still matches.

## Alternatives

| Option | Consequence |
| --- | --- |
| Require the current numeric generator pattern | Couples readers to one implementation and rejects previously accepted identities without a migration plan. Reject this option. |
| Introduce a versioned identifier grammar | Can support future semantics, but requires a format decision, compatibility rules, and migration evidence. Defer this option. |
| Keep opaque identifiers with explicit text validation | Matches current readers and migration. Select this option, subject to review. |

## Evidence and limits

The source baseline is the commit in frontmatter. These references describe static source inspection at that revision.

- [`valid_holder`](../../lib/030-time-refs-records.sh) checks a nonempty UTF-8 line without carriage return or line feed.
- [`validate_record`](../../lib/055-record-validation.sh) applies that rule to lock and semaphore acquisition fields.
- [`new_acquisition` and family rewrites](../../lib/080-families.sh) separate generated identity from later record versions.
- [Path release](../../lib/110-release.sh), [renewal](../../lib/140-extend.sh), and [semaphore operations](../../lib/170-semaphores.sh) define matching, stale, expiry, and absence results.
- [Offline migration](../../lib/185-migrate.sh) copies existing object references into the new state tree.
- [Release regressions](../../test/release-guards.py) cover malformed, stale, matching, omitted, and combined guards.
- [State coherence tests](../../test/state-coherence.py) check migration without object-identity changes.

[PR #123](https://github.com/git-stunts/locks/pull/123) corrected semaphore guard aliasing at this baseline.
Its full guarded suite passed, including 31 release-guard cases. The four RED failures represented three distinct failure scenarios.
This evidence does not prove that every historical deployment uses the current generator pattern.
The guarded `test/acquisition-identity.py` run passed four synthetic compatibility cases on 2026-10-05.
It tested path locks and semaphore slots with nonnumeric ASCII and Unicode identifiers.
Each case preserved the complete root through offline migration, preserved identity through a record rewrite, rejected stale guards, and released with the matching acquisition.
The fixtures include a combining character and retain its exact representation. They do not establish the contents of real historical stores.

## Implementation boundary

GL-007 must align the output schema, command reference, and event tables with this decision after acceptance.
It must express the text constraints without imposing the numeric generator pattern.
It must retain the nonnumeric stored-identity tests through migration, renewal, and guarded release for both reservation types.
It must add any missing cases required by schema or event-contract changes.
It must preserve exact identity bytes and the independent record/acquisition comparisons introduced by PR #123.
It must distinguish malformed input, absent authority, stale identity, expired renewal, and damaged stored records.

Changing the generator can remain compatible if readers continue to treat identities as opaque.
Any future restriction on accepted stored identities requires a separate compatibility decision and migration plan.
