import sys

from flexmeasures.cli import is_running as cli_is_running


def test_cli_is_running(app, monkeypatch):
    assert cli_is_running() is False
    monkeypatch.setattr(
        sys, "argv", ["/bin/flexmeasures", "add", "account", "--name", "XCorp."]
    )
    assert cli_is_running() is True
