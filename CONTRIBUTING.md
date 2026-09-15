# Contributing

- Tests are the spec. Write the failing case in `test/test.sh` first, show it red, then change `bin/git-locks`.
- `make lint` must pass with zero output: shellcheck with every optional check enabled, and shfmt with the repository's settings (`-i 2 -ci -bn`). Do not add a `# shellcheck disable` without a comment saying why.
- Pure bash and git only. No jq, no Python, no external daemons. Anything that would need one belongs in a different project.
- Keep `README.md` and `CHANGELOG.md` current in the same commit as the change they describe.
- Commits use conventional-commit subjects (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). No history rewriting on `main`.
- Configure the hooks once: `git config --local core.hooksPath scripts/hooks`. Pre-commit lints, pre-push runs the tests.
