from flask_security.core import current_user
from flask_security import login_required

from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.data.services.resources import get_assets
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


@flexmeasures_ui.route("/account", methods=["GET"])
@login_required
def account_view():
    return render_flexmeasures_template(
        "admin/account.html",
        logged_in_user=current_user,
        roles=",".join([role.name for role in current_user.roles]),
        num_assets=len(get_assets()),
    )
