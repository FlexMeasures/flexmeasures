from flask_security.core import current_user
from flask_security import login_required

from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.data.services.accounts import (
    get_number_of_assets_in_account,
    get_account_roles,
)
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


@flexmeasures_ui.route("/logged-in-user", methods=["GET"])
@login_required
def logged_in_user_view():
    """
    Basic information about the currently logged-in user.
    Plus basic actions (logout, reset pwd)
    """
    account_roles = get_account_roles(current_user.account_id)
    account_role_names = [account_role.name for account_role in account_roles]

    return render_flexmeasures_template(
        "admin/logged_in_user.html",
        logged_in_user=current_user,
        roles=",".join([role.name for role in current_user.roles]),
        num_assets=get_number_of_assets_in_account(current_user.account_id),
        account_role_names=account_role_names,
    )
