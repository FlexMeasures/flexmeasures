# This Makefile is deprecated. Please use the Poethepoet tasks or UV commands instead.
# See the documentation for more information about using the new setup: https://flexmeasures.readthedocs.io/latest/dev/setup-and-guidelines.html

# Check Python major and minor version
# For more information, see https://stackoverflow.com/a/22105036
# Not used anymore, as we now use the .python-version file to specify the Python version
# PYV = $(shell python -c "import sys;t='{v[0]}.{v[1]}'.format(v=list(sys.version_info[:2]));sys.stdout.write(t)")

# Note: use tabs
# actions which are virtual, i.e. not a script
.PHONY: install install-for-dev install-for-test install-deps install-flexmeasures test freeze-deps upgrade-deps update-docs generate-openapi show-file-space show-data-model clean-db cli-autocomplete build-highs-macos install-highs-macos

SEE_ABOVE_MSG = @echo "" && echo "Warning: See the deprecation notice above."

define POE_MSG
	@echo "Warning: this Make target has been superseded by a Poethepoet task (see pyproject.toml)."
	@echo "See the documentation for more information about using the new setup: https://flexmeasures.readthedocs.io/latest/dev/setup-and-guidelines.html"
	@echo "Running 'uv run poe $(1)' for you now ..."
	@echo ""
endef

define UV_MSG
	@echo "Warning: this Make target has been superseded by a simple UV command."
	@echo "See the documentation for more information about using the new setup: https://flexmeasures.readthedocs.io/latest/dev/setup-and-guidelines.html"
	@echo "Running '$(1)' for you now ..."
	@echo ""
endef

SEE_DOCUMENTATION_MSG = See the documentation for more information about using the new setup: https://flexmeasures.readthedocs.io/latest/dev/setup-and-guidelines.html
DEPRECATED_MSG = This command is no longer supported.
# ---- Development ---

test:
	$(call UV_MSG,uv sync --group test)
	uv sync --group test
	$(call POE_MSG,test)
	uv run poe test
	$(SEE_ABOVE_MSG)

# ---- Documentation ---

gen_code_docs := False # by default code documentation is not generated

# Note: this makes docs for the FlexMeasures project, free from custom settings and plugins
update-docs:
	$(call POE_MSG,update-docs)
	uv run poe update-docs
	$(SEE_ABOVE_MSG)

# Note: this will create SwaggerDocs with host-specific settings (e.g. platform name, support page, TOS) and plugins - use update-docs to make generic specs
generate-openapi:
	$(call POE_MSG,generate-open-api-specs)
	uv run poe generate-open-api-specs
	$(SEE_ABOVE_MSG)

# ---- Installation ---

install:
	$(call UV_MSG,uv sync)
	uv sync --group dev --group test
	$(SEE_ABOVE_MSG)

install-for-dev:
	$(call UV_MSG,uv sync --group dev --group test)
	uv sync --group dev --group test
	$(SEE_ABOVE_MSG)

install-for-test:
	$(call UV_MSG,uv sync --group test)
	uv sync --group test
	$(SEE_ABOVE_MSG)

build-highs-macos:
	@echo "$(DEPRECATED_MSG)"
	@echo "$(SEE_DOCUMENTATION_MSG)"

install-highs-macos:
	$(call UV_MSG,uv sync --group dev --group test)
	uv sync --group dev --group test
	$(SEE_ABOVE_MSG)

install-deps:
	ifneq ($(pinned), no)
		$(call UV_MSG,uv sync --group dev --group test)
		uv sync --group dev --group test
		$(SEE_ABOVE_MSG)
	else
		@echo "$(DEPRECATED_MSG)"
		@echo "To upgrade the lockfile, use 'uv lock --upgrade'.
		@echo "To upgrade ranges, manually upgrade them or use dependabot."
		@echo "$(SEE_DOCUMENTATION_MSG)"
	endif

install-flexmeasures:
	$(call UV_MSG,uv sync)
	uv sync
	$(SEE_ABOVE_MSG)

install-pip-tools:
	@echo "$(DEPRECATED_MSG)"
	@echo "Pip tools has been replaced by uv."
	@echo "$(SEE_DOCUMENTATION_MSG)"

install-docs-dependencies:
	$(call UV_MSG,uv sync --group docs)
	uv sync --group docs
	$(SEE_ABOVE_MSG)

freeze-deps:
	@echo "$(DEPRECATED_MSG)"
	@echo "Pip tools has been replaced by uv."
	@echo "$(SEE_DOCUMENTATION_MSG)"

upgrade-deps:
	@echo "$(DEPRECATED_MSG)"
	@echo "To upgrade the lockfile, use 'uv lock --upgrade'."
	@echo "To upgrade ranges, manually upgrade them or use dependabot."
	@echo "$(SEE_DOCUMENTATION_MSG)"

# ---- Data ----

show-file-space:
	$(call POE_MSG,show-file-space)
	uv run poe show-file-space
	$(SEE_ABOVE_MSG)

upgrade-db:
	$(call POE_MSG,upgrade-db)
	uv run poe upgrade-db
	$(SEE_ABOVE_MSG)

show-data-model:
	$(call POE_MSG,show-data-model)
	uv run poe show-data-model --uml
	$(SEE_ABOVE_MSG)

clean-db:
	$(call POE_MSG,clean-db)
	uv run poe clean-db
	$(SEE_ABOVE_MSG)

cli-autocomplete:
	$(call POE_MSG,cli-autocomplete)
	uv run poe cli-autocomplete
	$(SEE_ABOVE_MSG)