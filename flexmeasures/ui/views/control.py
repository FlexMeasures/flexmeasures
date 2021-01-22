from datetime import timedelta

from flask_security import roles_accepted

from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.utils import time_utils


# Control view
@flexmeasures_ui.route("/control", methods=["GET", "POST"])
@roles_accepted("admin", "Prosumer")
def control_view():
    """Control view.
    This page lists balancing opportunities for a selected time window.
    The user can place manual orders or choose to automate the ordering process.
    """
    next24hours = [
        (time_utils.get_most_recent_hour() + timedelta(hours=i)).strftime("%I:00 %p")
        for i in range(1, 26)
    ]
    return render_flexmeasures_template("views/control.html", next24hours=next24hours)
