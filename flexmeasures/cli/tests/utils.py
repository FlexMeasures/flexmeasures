from __future__ import annotations

from typing import Any, Callable
from traceback import print_tb

from click.core import Command as ClickCommand
from sqlalchemy import select

from flexmeasures import Account, Asset, Sensor, User
from flexmeasures.data import db


def check_command_ran_without_error(result):
    print(result)
    assert result.exit_code == 0, print_tb(
        result.exc_info[2]
    )  # run command without errors


def check_attribute_is_stored(
    db_object: Account | Asset | Sensor | User, attribute: str, value: Any
):
    assert (
        db.session.execute(select(type(db_object)).filter_by(id=db_object.id))
        .scalar_one_or_none()
        .attributes[attribute]
        == value
    )


def to_flags(cli_input: dict) -> list:
    """Turn dictionary of CLI input into a list of CLI flags ready for use in FlaskCliRunner.invoke().

    Example:
        cli_input = {
            "year": 2020,
            "country": "NL",
        }
        cli_flags = to_flags(cli_input)  # ["--year", 2020, "--country", "NL"]
        runner = app.test_cli_runner()
        result = runner.invoke(some_cli_function, to_flags(cli_input))
    """
    return [
        item
        for sublist in zip(
            [f"--{key.replace('_', '-')}" for key in cli_input.keys()],
            cli_input.values(),
        )
        for item in sublist
    ]


def get_click_commands(module) -> list[Callable]:
    return [
        getattr(module, attr)
        for attr in dir(module)
        if type(getattr(module, attr)) == ClickCommand
    ]
