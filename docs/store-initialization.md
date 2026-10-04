# Store initialization

A missing store is initialized automatically on first use, including `store`.
Use an absent path for a new store. An existing destination must already be a
valid bare Git repository, or the subject's common Git directory in `self` mode.
An empty directory, a directory containing unrelated files, and a file named
`HEAD` alone are not valid stores; git-locks refuses them without initializing
anything inside them.

Initialization prepares a bare repository in a unique temporary directory beside
the destination. Git templates are disabled so that a newly allocated store does
not copy template hooks, refs, or unrelated files. A completed directory is then
renamed into place on the same filesystem. A competing initializer can only
observe the absent destination or a completed store. It validates and uses the
winning repository, then normal root publication decides reservation admission.

Each initializer removes its unused preparation. On GNU and BSD systems, if a
competitor wins immediately before `mv`, the losing directory may be placed
inside the winning store; only that uniquely named preparation is removed. It
contains no reservations and is never read as authority. This handles both
portable `mv` destination forms without an external coordination service or a
persistent initialization lock.

Filesystem setup and initialization failures exit 2 with a structured
`store-write` error. Invalid existing destinations exit 2 with `store-read`.
Normal interruption cleans the preparation; a force-killed process can leave an
unreferenced `.git-locks.init.*` sibling or nested directory. Remove such a
preparation only after establishing that its initializer has stopped. Do not
move, replace, or remove the store while clients are using it.

Docker checks cover 15 rounds of four concurrent first-use claims, a forced
four-way directory-publication race, visibility while Git initialization is
paused, injected initialization failure, existing invalid destinations,
unwritable parents, exclusion of custom templates, and removal of unused
preparations. Every resulting race store is inspected through real Git-backed
commands.
