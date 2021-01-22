from datetime import timedelta

from flexmeasures.data.models.markets import Market
from flexmeasures.data.services.users import find_user_by_email


def get_asset_post_data() -> dict:
    post_data = {
        "name": "Test battery 2",
        "unit": "kW",
        "capacity_in_mw": 3,
        "event_resolution": timedelta(minutes=10).seconds / 60,
        "latitude": 30.1,
        "longitude": 100.42,
        "asset_type_name": "battery",
        "owner_id": find_user_by_email("test_prosumer@seita.nl").id,
        "market_id": Market.query.filter_by(name="epex_da").one_or_none().id,
    }
    return post_data
