# Note: use tabs
# actions which are virtual, i.e. not a script
.PHONY: install install-for-dev install-deps install-flexmeasures run-local test freeze-deps upgrade-deps update-docs update-docs-pdf show-file-space show-data-model


# ---- Development ---

run-local:
	python run-local.py

test:
	make install-for-dev
	pytest

# ---- Documentation ---

update-docs:
	pip3 install sphinx sphinx-rtd-theme sphinxcontrib.httpdomain
	cd documentation; make clean; make html; cd ..

update-docs-pdf:
	@echo "NOTE: PDF documentation requires packages (on Debian: latexmk texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended)"
	@echo "NOTE: Currently, the docs require some pictures which are not in the git repo atm. Ask the devs."
	pip3 install sphinx sphinxcontrib.httpdomain
	cd documentation; make clean; make latexpdf; make latexpdf; cd ..  # make latexpdf can require two passes

# ---- Installation ---

install: install-deps install-flexmeasures

install-for-dev:
	pip3 install -q pip-tools
	make freeze-deps
	pip-sync requirements/app.txt requirements/dev.txt requirements/test.txt
	make install-flexmeasures

install-deps:
	pip3 install -q pip-tools
	make freeze-deps
	pip-sync requirements/app.txt

install-flexmeasures:
	python setup.py develop

freeze-deps:
	pip3 install -q pip-tools
	pip-compile -o requirements/app.txt requirements/app.in
	pip-compile -o requirements/dev.txt requirements/dev.in
	pip-compile -o requirements/test.txt requirements/test.in

upgrade-deps:
	pip3 install -q pip-tools
	pip-compile --upgrade -o requirements/app.txt requirements/app.in
	pip-compile --upgrade -o requirements/dev.txt requirements/dev.in
	pip-compile --upgrade -o requirements/test.txt requirements/test.in
	make test


# ---- Data ----

show-file-space:
	# Where is our file space going?
	du --summarize --human-readable --total ./* ./.[a-zA-Z]* | sort -h

upgrade-db:
	flask db current
	flask db upgrade
	flask db current

show-data-model:
	./flexmeasures/data/scripts/visualize_data_model.py --uml --store  # also try with --schema for database model
