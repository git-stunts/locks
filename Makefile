SHELL := /usr/bin/env bash
# lib/*.sh are fragments of one script and only lint as the whole they build into (bin/git-locks).
SCRIPTS := bin/git-locks test/test.sh scripts/hooks/pre-commit scripts/hooks/pre-push scripts/build.sh scripts/benchmark-directory-tokens.sh test/directory-token-churn.sh
PREFIX ?= $(HOME)/.local

.PHONY: build lint test test-docker install uninstall

build: # assemble bin/git-locks from lib/*.sh and schema/git-locks.schema.json; commit the result with the lib change
	bash scripts/build.sh

lint:
	shellcheck -S style -o all $(SCRIPTS)
	shfmt -d -i 2 -ci -bn $(SCRIPTS)

test:
	bash test/test.sh
	bash test/directory-token-churn.sh

test-docker: # the same suite inside the official bash image, for a wall between the tests and your machine
	docker run --rm -v "$(CURDIR)":/src -w /src bash:5.2 bash -c 'apk add --no-cache git python3 py3-jsonschema >/dev/null && git config --global user.email t@example.invalid && git config --global user.name t && bash test/test.sh'

install:
	mkdir -p $(PREFIX)/bin
	rm -f $(PREFIX)/bin/git-locks
	install -m 0755 bin/git-locks $(PREFIX)/bin/git-locks

uninstall:
	rm -f $(PREFIX)/bin/git-locks
