from __future__ import annotations

from typing import Callable

from click.core import Command as ClickCommand


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
