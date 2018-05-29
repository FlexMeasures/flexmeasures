from flask_security.core import current_user
from flask_security import login_required

from bvp.ui.views import bvp_ui
from bvp.data.services import get_assets
from bvp.ui.utils.view_utils import render_bvp_template


@bvp_ui.route('/account', methods=['GET'])
@login_required
def account_view():
    return render_bvp_template("admin/account.html",
                               logged_in_user=current_user,
                               roles=",".join([role.name for role in current_user.roles]),
                               num_assets=len(get_assets()))
