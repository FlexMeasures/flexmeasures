# Check Python major and minor version
# For more information, see https://stackoverflow.com/a/22105036
PYV = $(shell python -c "import sys;t='{v[0]}.{v[1]}'.format(v=list(sys.version_info[:2]));sys.stdout.write(t)")
HIGHS_DIR = "../HiGHS"

# Note: use tabs
# actions which are virtual, i.e. not a script
.PHONY: install install-for-dev install-for-test install-deps install-flexmeasures run-local test freeze-deps upgrade-deps update-docs update-docs-pdf show-file-space show-data-model clean-db cli-autocomplete build-highs-macos install-highs-macos


# ---- Development ---

run-local:
	python run-local.py

test:
	make install-for-test
	pytest

# ---- Documentation ---

gen_code_docs := False # by default code documentation is not generated

update-docs:
	@echo "Creating docs environment ..."
	make install-docs-dependencies
	@echo "Creating documentation ..."
	export GEN_CODE_DOCS=${gen_code_docs}; cd documentation; make clean; make html SPHINXOPTS="-W --keep-going -n"; cd ..

update-docs-pdf:
	@echo "NOTE: PDF documentation requires packages (on Debian: latexmk texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended)"
	@echo "NOTE: Currently, the docs require some pictures which are not in the git repo atm. Ask the devs."
	make install-sphinx-tools

	export GEN_CODE_DOCS=${gen_code_docs}; cd documentation; make clean; make latexpdf; make latexpdf; cd ..  # make latexpdf can require two passes

# ---- Installation ---

install: install-deps install-flexmeasures

install-for-dev:
	make freeze-deps
	make ensure-deps-folder
	pip-sync requirements/${PYV}/app.txt requirements/${PYV}/dev.txt requirements/${PYV}/test.txt
	make install-flexmeasures

install-for-test:
	make install-pip-tools
# Pass pinned=no if you want to test against latest stable packages, default is our pinned dependency set
ifneq ($(pinned), no)
	pip-sync requirements/${PYV}/app.txt requirements/${PYV}/test.txt
else
	# cutting off the -c inter-layer dependency (that's pip-tools specific)
	tail -n +3 requirements/test.in >> temp-test.in
	pip install --upgrade -r requirements/app.in -r temp-test.in
	rm temp-test.in
endif
	make install-flexmeasures
# Locally install HiGS on macOS
	if [ "$(shell uname)" = "Darwin" ]; then \
		make install-highs-macos; \
	fi

$(HIGHS_DIR):
	if [ ! -d $(HIGHS_DIR) ]; then \
		git clone https://github.com/ERGO-Code/HiGHS.git $(HIGHS_DIR); \
	fi
	brew install cmake;

build-highs-macos: $(HIGHS_DIR)
	cd $(HIGHS_DIR); \
	git checkout latest; \
	mkdir -p build; \
	cd build; \
	cmake ..; \
	make; \
	make install; \
	cd ../../flexmeasures;

install-highs-macos: build-highs-macos
	pip install $(HIGHS_DIR) ; \

install-deps:
	make install-pip-tools
	make freeze-deps
# Pass pinned=no if you want to test against latest stable packages, default is our pinned dependency set
ifneq ($(pinned), no)
	pip-sync requirements/${PYV}/app.txt
else
	pip install --upgrade -r requirements/app.in
endif

install-flexmeasures:
	pip install -e .

install-pip-tools:
	pip3 install -q "pip-tools>=7.2"

install-docs-dependencies:
	pip install -r requirements/${PYV}/docs.txt

freeze-deps:
	make ensure-deps-folder
	make install-pip-tools
	pip-compile -o requirements/${PYV}/app.txt requirements/app.in
	pip-compile -c requirements/${PYV}/app.txt -o requirements/${PYV}/test.txt requirements/test.in
	pip-compile -c requirements/${PYV}/app.txt -c requirements/${PYV}/test.txt -o requirements/${PYV}/dev.txt requirements/dev.in
	pip-compile -c requirements/${PYV}/app.txt -o requirements/${PYV}/docs.txt requirements/docs.in

upgrade-deps:
	make ensure-deps-folder
	make install-pip-tools
	pip-compile --upgrade -o requirements/${PYV}/app.txt requirements/app.in
	pip-compile --upgrade -c requirements/${PYV}/app.txt -o requirements/${PYV}/test.txt requirements/test.in
	pip-compile --upgrade -c requirements/${PYV}/app.txt -c requirements/${PYV}/test.txt -o requirements/${PYV}/dev.txt requirements/dev.in
	pip-compile --upgrade -c requirements/${PYV}/app.txt -o requirements/${PYV}/docs.txt requirements/docs.in

ifneq ($(skip-test), yes)
	make test
endif

# ---- Data ----

show-file-space:
	# Where is our file space going?
	du --summarize --human-readable --total ./* ./.[a-zA-Z]* | sort -h

upgrade-db:
	flask db current
	flask db upgrade
	flask db current

show-data-model:
	# This generates the data model, as currently written in code, as a PNG picture.
	# Also try with --schema for the database model. 
	# With --deprecated, you'll see the legacy models, and not their replacements.
	# Use --help to learn more. 
	./flexmeasures/data/scripts/visualize_data_model.py --uml

ensure-deps-folder:
	mkdir -p requirements/${PYV}

clean-db:
	./flexmeasures/data/scripts/clean_database.sh ${db_name} ${db_user}

cli-autocomplete:
	./flexmeasures/cli/scripts/add_scripts_path.sh ${extension}
