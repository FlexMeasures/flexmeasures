from flask import Flask

from flexmeasures.utils.plugin_utils import register_plugins


def test_register_plugins_error_hints_at_comma_separated_format(caplog):
    """Failing to import an unrecognised plugin should hint at the expected
    comma-separated format, so a malformed setting (e.g. a JSON array) doesn't
    read as a packaging problem."""
    app = Flask(__name__)
    app.config["FLEXMEASURES_PLUGINS"] = '["flexmeasures_entsoe"]'
    register_plugins(app)
    errors = [
        record.message
        for record in caplog.records
        if "comma-separated" in record.message
    ]
    assert errors
