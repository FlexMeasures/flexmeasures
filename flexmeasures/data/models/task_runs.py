from datetime import datetime
import pytz

from sqlalchemy import select

from flexmeasures.data import db


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

    @staticmethod
    def record_run(task_name: str, status: bool):
        """
        Record the latest task run (overwriting previous ones).
        If the row is not yet in the table, create it first.
        Does not commit.
        """
        task_run = db.session.execute(
            select(LatestTaskRun).filter(LatestTaskRun.name == task_name)
        ).scalar_one_or_none()
        if task_run is None:
            task_run = LatestTaskRun(name=task_name)
            db.session.add(task_run)
        task_run.datetime = datetime.utcnow().replace(tzinfo=pytz.utc)
        task_run.status = status
