from datetime import timedelta
from isodate import parse_duration

import bvp.data.models


def test_resolutions():
    assert len(bvp.data.models.resolutions) == 4


def test_users(app):
    # TODO: importing before the app fixture is executed fails as db is still None. We might be able to do better.
    from bvp.data.models.user import User

    users = User.query.all()
    assert len(users) > 0


def test_prices_horizons(app):
    from bvp.data.models.markets import Price

    prices = Price.query.all()
    assert len(prices) > 0
    for price in prices:
        assert type(parse_duration(price.horizon)) == timedelta
