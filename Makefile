SHELL := /usr/bin/env bash
SCRIPTS := bin/git-locks test/test.sh scripts/hooks/pre-commit scripts/hooks/pre-push
PREFIX ?= $(HOME)/.local

.PHONY: lint test test-docker install uninstall

lint:
	shellcheck -S style -o all $(SCRIPTS)
	shfmt -d -i 2 -ci -bn $(SCRIPTS)

test:
	bash test/test.sh

test-docker: # the same suite inside the official bash image, for a wall between the tests and your machine
	docker run --rm -v "$(CURDIR)":/src -w /src bash:5.2 bash -c 'apk add --no-cache git python3 py3-jsonschema >/dev/null && git config --global user.email t@example.invalid && git config --global user.name t && bash test/test.sh'

install:
	mkdir -p $(PREFIX)/bin
	rm -f $(PREFIX)/bin/git-locks
	install -m 0755 bin/git-locks $(PREFIX)/bin/git-locks

uninstall:
	rm -f $(PREFIX)/bin/git-locks
