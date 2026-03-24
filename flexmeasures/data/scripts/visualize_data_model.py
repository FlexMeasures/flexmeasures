#!/usr/bin/env python
import argparse
import sys
from getpass import getpass
import inspect
from importlib import import_module

import pkg_resources
from sqlalchemy import MetaData
from sqlalchemy.orm import class_mapper

"""
This is our dev script to make images displaying our data model.

At the moment, this code requires an unreleased version of sqlalchemy_schemadisplay, install it like this:

    pip install git+https://github.com/fschulze/sqlalchemy_schemadisplay.git@master


See also https://github.com/fschulze/sqlalchemy_schemadisplay/issues/21

For rendering of graphs (instead of saving a PNG), you'll need pillow:

    pip install pillow

"""

DEBUG = True

# List here modules which should be scanned for the UML version
RELEVANT_MODULES = [
    "task_runs",
    "data_sources",
    "generic_assets",
    "user",
    "time_series",
]

# List here tables in the data model which are currently relevant
RELEVANT_TABLES = [
    "role",
    "account",
    "account_role",
    "fm_user",
    "data_source",
    "latest_task_run",
    "generic_asset_type",
    "generic_asset",
    "sensor",
    "timed_belief",
    "timed_value",
]

# The following two lists are useful for transition periods, when some tables are legacy, and some have been added.
# This allows you to show the old model as well as the future model.
LEGACY_TABLES = []
RELEVANT_TABLES_NEW = []


def check_sqlalchemy_schemadisplay_installation():
    """Make sure the library which translates the model into a graph structure
    is installed with the right version."""
    try:
        import sqlalchemy_schemadisplay  # noqa: F401
    except ImportError:
        print(
            "You need to install sqlalchemy_schemadisplay==1.4dev0 or higher.\n"
            "Try this: pip install git+https://github.com/fschulze/sqlalchemy_schemadisplay.git@master"
        )
        sys.exit(0)

    packages_versions = {p.project_name: p.version for p in pkg_resources.working_set}
    if packages_versions["sqlalchemy-schemadisplay"] < "1.4":
        print(
            "Your version of sqlalchemy_schemadisplay is too small. Should be 1.4 or higher."
            " Currently, only 1.4dev0 is available with needed features.\n"
            "Try this: pip install git+https://github.com/fschulze/sqlalchemy_schemadisplay.git@master"
        )
        sys.exit(0)


def uses_dot(func):
    """
    Decorator to make sure that if dot/graphviz (for drawing the graph)
    is not installed there is a proper message.
    """

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as fnfe:
            if '"dot" not found in path' in str(fnfe):
                print(fnfe)
                print("Try this (on debian-based Linux): sudo apt install graphviz")
                sys.exit(2)
            else:
                raise

    return wrapper


@uses_dot
def create_schema_pic(
    pg_url, pg_user, pg_pwd, store: bool = False, deprecated: bool = False
):
    """Create a picture of the SCHEMA of relevant tables."""
    print("CREATING SCHEMA PICTURE ...")
    print(
        f"Connecting to database {pg_url} as user {pg_user} and loading schema metadata ..."
    )
    db_metadata = MetaData(f"postgresql://{pg_user}:{pg_pwd}@{pg_url}")
    relevant_tables = RELEVANT_TABLES
    if deprecated:
        relevant_tables += LEGACY_TABLES
    else:
        relevant_tables += RELEVANT_TABLES_NEW
    kwargs = dict(
        metadata=db_metadata,
        show_datatypes=False,  # The image would get nasty big if we'd show the datatypes
        show_indexes=False,  # ditto for indexes
        rankdir="LR",  # From left to right (instead of top to bottom)
        concentrate=False,  # Don't try to join the relation lines together
        restrict_tables=relevant_tables,
    )
    print("Creating the pydot graph object...")
    if DEBUG:
        print(f"Relevant tables: {relevant_tables}")
    graph = create_schema_graph(**kwargs)
    if store:
        print("Storing as image (db_schema.png) ...")
        graph.write_png("db_schema.png")  # write out the file
    else:
        show_image(graph)


@uses_dot
def create_uml_pic(store: bool = False, deprecated: bool = False):
    print("CREATING UML CODE DIAGRAM ...")
    print("Finding all the relevant mappers in our model...")
    mappers = []
    # map comparable names to model classes. We compare without "_" and in lowercase.
    # Note: This relies on model classes and their tables having the same name,
    #       ignoring capitalization and underscores.
    relevant_models = {}
    for module in RELEVANT_MODULES:
        relevant_models.update(
            {
                mname.lower(): mclass
                for mname, mclass in inspect.getmembers(
                    import_module(f"flexmeasures.data.models.{module}")
                )
                if inspect.isclass(mclass) and issubclass(mclass, flexmeasures_db.Model)
            }
        )
    relevant_tables = RELEVANT_TABLES
    if deprecated:
        relevant_tables += LEGACY_TABLES
    else:
        relevant_tables += RELEVANT_TABLES_NEW
    if DEBUG:
        print(f"Relevant tables: {relevant_tables}")
        print(f"Relevant models: {relevant_models}")
    matched_models = {
        m: c for (m, c) in relevant_models.items() if c.__tablename__ in relevant_tables
    }
    for model_name, model_class in matched_models.items():
        if DEBUG:
            print(f"Loading class {model_class.__name__} ...")
        mappers.append(class_mapper(model_class))

    print("Creating diagram ...")
    kwargs = dict(
        show_operations=False,  # not necessary in this case
        show_multiplicity_one=False,  # some people like to see the ones, some don't
    )
    print("Creating the pydot graph object...")
    graph = create_uml_graph(mappers, **kwargs)
    if store:
        print("Storing as image (uml_diagram.png) ...")
        graph.write_png("uml_diagram.png")  # write out the file
    else:
        show_image(graph)


@uses_dot
def show_image(graph):
    """
    Show an image created through sqlalchemy_schemadisplay.

    We could also have used functions in there, but:
    https://github.com/fschulze/sqlalchemy_schemadisplay/pull/14

    Anyways, this is a good place to check for PIL and those two functions
    were containing almost identical logic - these two lines here are
    an improvement.
    """
    from io import BytesIO

    try:
        from PIL import Image
    except ImportError:
        print("Please pip-install the pillow library in order to show graphs.")
        sys.exit(0)

    print("Creating PNG stream ...")
    iostream = BytesIO(graph.create_png())

    print("Showing image ...")
    Image.open(iostream).show()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("--help")
    if DEBUG:
        print("DEBUG is on")

    check_sqlalchemy_schemadisplay_installation()
    from sqlalchemy_schemadisplay import create_schema_graph, create_uml_graph

    parser = argparse.ArgumentParser(
        description="Visualize our data model. Creates image files."
    )
    parser.add_argument(
        "--schema", action="store_true", help="Visualize the data model schema."
    )
    parser.add_argument(
        "--uml",
        action="store_true",
        help="Visualize the relationships available in code (UML style).",
    )
    parser.add_argument(
        "--deprecated",
        action="store_true",
        help="If given, include the parts of the depcrecated data model, and leave out their new counterparts.",
    )
    parser.add_argument(
        "--store",
        action="store_true",
        help="Store the images as files, instead of showing them directly (which requires pillow).",
    )
    parser.add_argument(
        "--pg_url",
        help="Postgres URL (needed if --schema is on).",
        default="localhost:5432/flexmeasures",
    )
    parser.add_argument(
        "--pg_user",
        help="Postgres user (needed if --schema is on).",
        default="flexmeasures",
    )

    args = parser.parse_args()

    if args.schema:
        pg_pwd = getpass(f"Please input the postgres password for user {args.pg_user}:")
        create_schema_pic(
            args.pg_url,
            args.pg_user,
            pg_pwd,
            store=args.store,
            deprecated=args.deprecated,
        )
    elif args.uml:
        try:
            from flexmeasures.data import db as flexmeasures_db
        except ImportError as ie:
            print(
                f"We need flexmeasures.data to be in the path, so we can read the data model. Error: '{ie}''."
            )
            sys.exit(0)
        create_uml_pic(store=args.store, deprecated=args.deprecated)
    else:
        print("Please specify either --uml or --schema. What do you want to see?")
