SHELL := /usr/bin/env bash
SCRIPTS := bin/git-locks test/test.sh scripts/hooks/pre-commit scripts/hooks/pre-push
PREFIX ?= $(HOME)/.local

.PHONY: lint test install uninstall

lint:
	shellcheck -S style -o all $(SCRIPTS)
	shfmt -d -i 2 -ci -bn $(SCRIPTS)

test:
	bash test/test.sh

install:
	mkdir -p $(PREFIX)/bin
	rm -f $(PREFIX)/bin/git-locks
	install -m 0755 bin/git-locks $(PREFIX)/bin/git-locks

uninstall:
	rm -f $(PREFIX)/bin/git-locks
