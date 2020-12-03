# Note: use tabs
# actions which are virtual, i.e. not a script
.PHONY: install install-for-dev install-deps install-bvp run-local test freeze-deps upgrade-deps update-docs update-docs-pdf show-file-space show-data-model


run-local:
	python bvp/run-local.py

test:
	make install-for-dev
	pytest

update-docs:
	pip install sphinx sphinxcontrib.httpdomain
	cd documentation; make clean; make html; cd ..

update-docs-pdf:
	apt-get install texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended 
	# note: requires some pictures not in the git repo atm
	cd documentation; make clean; make latexpdf; cd ..

# ---- Installation ---

install: install-deps install-bvp

install-for-dev:
	pip install -q pip-tools
	make freeze-deps
	pip-sync requirements/app.txt requirements/dev.txt requirements/test.txt
	make install-bvp

install-deps:
	pip install -q pip-tools
	make freeze-deps
	pip-sync requirements/app.txt

install-bvp:
	python setup.py develop

freeze-deps:
	pip install -q pip-tools
	pip-compile -o requirements/app.txt requirements/app.in
	pip-compile -o requirements/dev.txt requirements/dev.in
	pip-compile -o requirements/test.txt requirements/test.in

upgrade-deps:
	pip install -q pip-tools
	pip-compile --upgrade -o requirements/app.txt requirements/app.in
	pip-compile --upgrade -o requirements/dev.txt requirements/dev.in
	pip-compile --upgrade -o requirements/test.txt requirements/test.in


# ---- Data Model ----

show-file-space:
	# Where is our file space going?
	du --summarize --human-readable --total ./* ./.[a-zA-Z]* | sort -h

upgrade-db:
	flask db current
	flask db upgrade
	flask db current

show-data-model:
	./bvp/data/scripts/visualize_data_model.py --uml --store # also try with --schema for database model
