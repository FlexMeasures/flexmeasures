from datetime import timedelta

from flask_security import roles_accepted

from views import bvp_views
from utils.view_utils import render_bvp_template
from utils import time_utils


# Control view
@bvp_views.route('/control', methods=['GET', 'POST'])
@roles_accepted("admin", "asset-owner")
def control_view():
    """ Control view.
    This page lists balancing opportunities for a selected time window.
    The user can place manual orders or choose to automate the ordering process.
    """
    next24hours = [(time_utils.get_most_recent_hour() + timedelta(hours=i)).strftime("%I:00 %p") for i in range(1, 26)]
    return render_bvp_template("views/control.html",
                               next24hours=next24hours)
