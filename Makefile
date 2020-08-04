# Note: use tabs
# actions which are virtual, i.e. not a script
.PHONY: install install-deps install-bvp run-local test freeze-deps show-file-space

install: install-deps install-bvp

install-deps:
	pip install pip-tools
	pip-sync

freeze-deps:
	pip install pip-tools
	pip-compile  # use --upgrade or --upgrade-package to actually change versions 

install-bvp:
	python setup.py develop

run-local:
	python bvp/run-local.py

test:
	python setup.py test

upgrade-db:
	flask db current
	flask db upgrade

update-docs:
	pip install sphinx sphinxcontrib.httpdomain
	cd documentation; make clean; make html; cd ..

show-file-space:
	# Where is our file space going?
	du --summarize --human-readable --total ./* ./.[a-zA-Z]* | sort -h
