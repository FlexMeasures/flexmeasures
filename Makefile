# Note: use tabs
# actions which are virtual, i.e. not a script
.PHONY: install install-deps install-bvp run-local test freeze-deps upgrade-deps show-file-space

install: install-deps install-bvp

install-deps:
	pip install -q pip-tools
	make freeze-deps
	pip-sync requirements/app.txt

install-deps-with-dev:
	pip install -q pip-tools
	make freeze-deps
	pip-sync requirements/app.txt requirements/dev.txt requirements/test.txt

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

install-bvp:
	python setup.py develop

run-local:
	python bvp/run-local.py

test:
	make install-deps-with-dev
	pytest

upgrade-db:
	flask db current
	flask db upgrade
	flask db current

update-docs:
	pip install sphinx sphinxcontrib.httpdomain
	cd documentation; make clean; make html; cd ..

show-file-space:
	# Where is our file space going?
	du --summarize --human-readable --total ./* ./.[a-zA-Z]* | sort -h
