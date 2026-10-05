SHELL := /usr/bin/env bash
# lib/*.sh are fragments of one script and only lint as the whole they build into (bin/git-locks).
SCRIPTS := bin/git-locks test/test.sh test/family-replacement.sh test/literal-paths.sh test/unicode-locale.sh test/unicode-locale-calibration.sh test/observation/git-shim.sh test/directory-token-churn.sh test/unicode-missing-locale.sh examples/cooperating-workers/demo.sh examples/cooperating-workers/worker.sh scripts/hooks/pre-commit scripts/hooks/pre-push scripts/build.sh scripts/benchmark-directory-tokens.sh scripts/require-docker.sh scripts/docker-entry.sh
PREFIX ?= $(HOME)/.local

.PHONY: build lint lint-container test test-container test-docker study-observation test-observation-calibration install uninstall

build: # assemble bin/git-locks from lib/*.sh and schema/git-locks.schema.json; commit the result with the lib change
	bash scripts/build.sh

lint:
	python3 scripts/docker-run.py make lint-container

lint-container:
	node scripts/require-docker.mjs
	shellcheck -S style -o all $(SCRIPTS)
	shfmt -d -i 2 -ci -bn $(SCRIPTS)

test test-docker:
	python3 scripts/docker-run.py make test-container

test-container:
	node scripts/require-docker.mjs
	python3 test/docker-boundary.py
	python3 test/docker-resources.py
	python3 test/state-coherence.py
	python3 test/root-refs.py
	python3 test/test-hooks.py
	python3 test/utf8-json.py
	python3 test/nul-streams.py
	python3 test/time-arithmetic.py
	python3 test/store-failures.py
	python3 test/store-bootstrap.py
	python3 test/store-hooks.py
	python3 test/store-environment.py
	python3 test/store-selection.py
	python3 test/store-home.py
	python3 test/help-synopses.py
	python3 test/build-help.py
	python3 scripts/roadmap.py --check
	python3 test/planning-graph.py
	python3 test/store-integrity.py
	python3 test/doctor-findings.py
	python3 test/renewal.py
	python3 test/release-guards.py
	python3 test/acquisition-identity.py
	python3 test/wrapper-lifecycle.py
	bash test/test.sh
	python3 test/capacity.py
	bash test/literal-paths.sh
	bash test/unicode-locale.sh
	bash test/unicode-locale-calibration.sh
	bash test/directory-token-churn.sh
	python3 test/observation/study.py --output /work/artifacts/observation-$$(date +%s)-$$$$
	python3 test/root-cas-calibration.py

# The study deliberately returns 1 if it exposes a production invariant hole.
# Choose a fresh output directory; retained receipts are never overwritten.
OBSERVATION_OUT ?= /work/artifacts/git-locks-observation

study-observation:
	python3 scripts/docker-run.py python3 test/observation/study.py --output "$(OBSERVATION_OUT)"

test-observation-calibration:
	python3 scripts/docker-run.py python3 test/observation/study.py --calibrate-only --output "$(OBSERVATION_OUT)-calibration"

install:
	mkdir -p $(PREFIX)/bin
	rm -f $(PREFIX)/bin/git-locks
	install -m 0755 bin/git-locks $(PREFIX)/bin/git-locks

uninstall:
	rm -f $(PREFIX)/bin/git-locks
