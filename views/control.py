from datetime import timedelta

from flask import session

from views import bvp_views
from views.utils import render_bvp_template, check_prosumer_mock
from utils import time_utils


# Control view
@bvp_views.route('/control', methods=['GET', 'POST'])
def control_view():
    """ Control view.
    This page lists balancing opportunities for a selected time window.
    The user can place manual orders or choose to automate the ordering process.
    """
    check_prosumer_mock()
    next24hours = [(time_utils.get_most_recent_hour() + timedelta(hours=i)).strftime("%I:00 %p") for i in range(1, 26)]
    return render_bvp_template("control.html",
                               next24hours=next24hours,
                               prosumer_mock=session.get("prosumer_mock", "0"))
