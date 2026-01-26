from __future__ import annotations

from traceback import print_tb

import click


def exception_reporter(job, exc_type, exc_value, traceback):
    print_tb(traceback)
    click.echo("HANDLING RQ WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value))
