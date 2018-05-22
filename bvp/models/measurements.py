from bvp.database import db


class Measurement(db.Model):
    """
    All measurements are stored in one slim table.
    TODO: datetime objects take up most of the space (12 bytes each)). One way out is to normalise them out to a table.
    TODO: If there are more than one measurements per asset per time step possible, we can expand rather easily.
    """

    datetime = db.Column(db.DateTime(timezone=True), primary_key=True)
    asset_id = db.Column(db.Integer(), db.ForeignKey('asset.id'), primary_key=True)
    value = db.Column(db.Float, nullable=False)

    asset = db.relationship('Asset', backref=db.backref('measurements', lazy=True))
