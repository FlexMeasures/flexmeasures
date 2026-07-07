"""This module hosts the views. This file registers blueprints and hosts some helpful functions"""

from flexmeasures.ui import flexmeasures_ui

# Now views can register
from flexmeasures.ui.views.dashboard import dashboard_view  # noqa: F401

from flexmeasures.ui.views.users.logged_in_user import (  # noqa: F401  # noqa: F401
    logged_in_user_view,
)


# Shared label/description for the "attributes" JSON field.
# Imported by sensor and account views so the text is defined exactly once.
# Actually, attributes are edited not in the form itself anymore, but in their own modal dialogue.
ATTRIBUTES_FIELD_LABEL = "Other attributes (JSON)"
ATTRIBUTES_FIELD_DESCRIPTION = (
    "Custom attributes as JSON, for custom functionality, e.g. used in plugins."
)


@flexmeasures_ui.route("/docs")
def docs_view():
    """Render the Sphinx documentation"""
    # Todo: render the docs with this nicer url and include the app's navigation menu
    return
