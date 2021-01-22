from datetime import datetime
import pytz

from flexmeasures.data.config import db


class LatestTaskRun(db.Model):
    """ "
    Log the (latest) running of a task.
    This is intended to be used for live monitoring. For a full analysis,
    there are log files.
    """

    name = db.Column(db.String(80), primary_key=True)
    datetime = db.Column(
        db.DateTime(timezone=True), default=datetime.utcnow().replace(tzinfo=pytz.utc)
    )
    status = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return "<TaskRun [%s] at %s (status: %s)>" % (
            self.name,
            self.datetime,
            {True: "ok", False: "err"}[self.status],
        )
