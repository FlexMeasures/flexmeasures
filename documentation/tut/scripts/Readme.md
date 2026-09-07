# Scripts to run tutorials

The tutorials in the docs are for you to run step by step, command by command,
so that every step clarifies more of what FlexMeasures is for, and what it can do for you.

However, sometimes one might want to run through them all.
We scripted the tutorials so they can be automated. They don't come with a guarantee.

For us, they are also a step in [our release checklist](https://github.com/FlexMeasures/tsc/blob/main/RELEASE.md) before we upload a new version to PyPI.

We run these tests in the Docker Compose stack:

    docker compose build
    docker compose up --detach --wait
    ./documentation/tut/scripts/run-tutorial-in-docker.sh
    ./documentation/tut/scripts/run-tutorial2-in-docker.sh
    ./documentation/tut/scripts/run-tutorial3-in-docker.sh
    ./documentation/tut/scripts/run-tutorial4-in-docker.sh
    ./documentation/tut/scripts/run-tutorial5-in-docker.sh
    ./documentation/tut/scripts/run-data-ingestion-in-docker.sh

- One still needs to check the output (no errors?) and plotted data (plots like we expect?)
- The toy tutorial runners use `flexmeasures add toy-account --shell-vars`, so they no longer depend on fixed numeric IDs. Tutorials 1-5 still run in chapter order because later tutorials use data created by earlier ones.
- The data-ingestion runner is standalone. It obtains the toy sensor ID through `--shell-vars` when needed and verifies the values it writes.
- Need to start over? Run `docker compose down --volumes`, then rebuild and start the Compose stack.
- We try to keep these scripts in sync with the tutorials. But as you can imagine, this is hard, as is keeping docs up to date in general.
- At least, this might see some regular use by us. The tutorial in the docs sees more usage by new users, who sometimes tell us what they found.
