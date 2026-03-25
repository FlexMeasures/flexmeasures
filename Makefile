# This Makefile is deprecated. Please use the Poethepoet tasks or UV commands instead.
# See the documentation for more information about using the new setup: https://flexmeasures.readthedocs.io/latest/dev/setup-and-guidelines.html

# Note: use tabs
# actions which are virtual, i.e. not a script
.PHONY: install install-for-dev install-for-test install-deps install-flexmeasures install-pip-tools install-docs-dependencies install-highs-macos build-highs-macos test freeze-deps upgrade-deps upgrade-db update-docs generate-openapi show-file-space show-data-model clean-db cli-autocomplete

DOCS_URL = https://flexmeasures.readthedocs.io/latest/dev/setup-and-guidelines.html

define WARN_DEPRECATED
	@echo "Warning: 'make $@' has now been implemented by uv and poe commands. The Makefile will be deprecated in favour of poe soon."
	@echo "See: $(DOCS_URL)"
	@echo ""
endef

define CHECK_UV
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "You seem to not have installed your environment via uv. We advise to do that soon for a seamless developer experience."; \
		echo "Take a look at the new setup here: $(DOCS_URL)"; \
		exit 1; \
	fi
endef

# ---- Development ---

test:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv sync --group test
	uv run poe test
	$(WARN_DEPRECATED)

# ---- Documentation ---

# Note: this makes docs for the FlexMeasures project, free from custom settings and plugins
update-docs:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv run poe update-docs
	$(WARN_DEPRECATED)

# Note: this will create SwaggerDocs with host-specific settings (e.g. platform name, support page, TOS) and plugins - use update-docs to make generic specs
generate-openapi:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv run poe generate-open-api-specs
	$(WARN_DEPRECATED)

# ---- Installation ---

install:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv sync --group dev --group test
	$(WARN_DEPRECATED)

install-for-dev:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv sync --group dev --group test
	$(WARN_DEPRECATED)

install-for-test:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv sync --group test
	$(WARN_DEPRECATED)

install-flexmeasures:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv sync
	$(WARN_DEPRECATED)

install-docs-dependencies:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv sync --group docs
	$(WARN_DEPRECATED)

install-highs-macos:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv sync --group dev --group test
	$(WARN_DEPRECATED)

build-highs-macos:
	@echo "This command is no longer supported."
	@echo "See: $(DOCS_URL)"

install-deps:
ifeq ($(pinned), no)
	@echo "This command is no longer supported for unpinned installs."
	@echo "To upgrade the lockfile, use 'uv lock --upgrade'."
	@echo "To upgrade ranges, manually upgrade them or use dependabot."
	@echo "See: $(DOCS_URL)"
else
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv sync --group dev --group test
	$(WARN_DEPRECATED)
endif

install-pip-tools:
	@echo "This command is no longer supported. Pip tools has been replaced by uv."
	@echo "See: $(DOCS_URL)"

freeze-deps:
	@echo "This command is no longer supported. Pip tools has been replaced by uv."
	@echo "See: $(DOCS_URL)"

upgrade-deps:
	@echo "This command is no longer supported."
	@echo "To upgrade the lockfile, use 'uv lock --upgrade'."
	@echo "To upgrade ranges, manually upgrade them or use dependabot."
	@echo "See: $(DOCS_URL)"

# ---- Data ----

show-file-space:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv run poe show-file-space
	$(WARN_DEPRECATED)

upgrade-db:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv run poe upgrade-db
	$(WARN_DEPRECATED)

show-data-model:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv run poe show-data-model --uml
	$(WARN_DEPRECATED)

clean-db:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv run poe clean-db
	$(WARN_DEPRECATED)

cli-autocomplete:
	$(WARN_DEPRECATED)
	$(CHECK_UV)
	uv run poe cli-autocomplete
	$(WARN_DEPRECATED)
