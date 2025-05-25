# Scripts to run tutorials

The tutorials in the docs are for you to run step by step, command by command,
so that every step clarifies more of what FlexMeasures is for, and what it can do for you.

However, sometimes one might want to run through them all.
We scripted the tutorials, so they can be automated. They don't come with a guarantee.

For us, they are actually a step in [our release checklist](https://github.com/FlexMeasures/tsc/blob/main/RELEASE.md) before we upload a new version to Pypi.

We run these tests in the docker compose stack:

    docker compose build
    docker compose up
    ./documentation/tut/scripts/run-tutorial-in-docker.sh
    ./documentation/tut/scripts/run-tutorial2-in-docker.sh
    ./documentation/tut/scripts/run-tutorial3-in-docker.sh
    ./documentation/tut/scripts/run-tutorial4-in-docker.sh

- One still needs to check the output (no errors?) and plotted data (plots like we expect?)
- These need to be run in order so the sensor IDs match (just like when you run them from the docs)
- Need to start over? `docker rm --force flexmeasures-dev-db-1`, then `down` and `up` with your compose stack..
- We try to keep these script in sync with the tutorials. But as you can imagine, this is hard, as is keeping docs up to date in general.
- At least, this might see some regular use by us. The tutorial in the docs sees more usage by new users, who sometimes tell us what they found.
