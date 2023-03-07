import pytest

from flexmeasures.utils.entity_address_utils import (
    build_entity_address,
    parse_entity_address,
    EntityAddressException,
    build_ea_scheme_and_naming_authority,
    reverse_domain_name,
)
from flexmeasures.utils.time_utils import get_first_day_of_next_month


@pytest.mark.parametrize(
    "info, entity_type, host, fm_scheme, exp_result",
    [
        (
            dict(sensor_id=42),
            "sensor",
            "flexmeasures.io",
            "fm1",
            "ea1.2021-01.io.flexmeasures:fm1.42",
        ),
        (
            dict(asset_id=42),
            "sensor",
            "flexmeasures.io",
            "fm1",
            "required field 'sensor_id'",
        ),
        (
            dict(sensor_id=40),
            "connection",
            "flexmeasures.io",
            "fm1",
            "ea1.2021-01.io.flexmeasures:fm1.40",
        ),
        (
            dict(asset_id=40),
            "connection",
            "flexmeasures.io",
            "fm1",
            "required field 'sensor_id'",
        ),
        (
            dict(owner_id=3, asset_id=40),
            "connection",
            "flexmeasures.io",
            "fm0",
            "ea1.2021-01.io.flexmeasures:fm0.3:40",
        ),
        (
            dict(owner_id=3),
            "connection",
            "flexmeasures.io",
            "fm0",
            "required field 'asset_id'",
        ),
        (
            dict(owner_id=40, asset_id=30),
            "connection",
            "localhost:5000",
            "fm0",
            f"ea1.{get_first_day_of_next_month().strftime('%Y-%m')}.localhost:fm0.40:30",
        ),
        (
            dict(
                weather_sensor_type_name="temperature",
                latitude=52,
                longitude=73.0,
            ),
            "weather_sensor",
            "flexmeasures.io",
            "fm0",
            "ea1.2021-01.io.flexmeasures:fm0.temperature:52:73.0",
        ),
        (
            dict(market_name="epex_da"),
            "market",
            "flexmeasures.io",
            "fm0",
            "ea1.2021-01.io.flexmeasures:fm0.epex_da",
        ),
        (
            dict(
                owner_id=40,
                asset_id=30,
                event_type="soc",
                event_id=302,
            ),
            "event",
            "http://staging.flexmeasures.io:4444",
            "fm0",
            "ea1.2022-09.io.flexmeasures.staging:fm0.40:30:302:soc",
        ),
    ],
)
def test_build_entity_address(
    app, info: dict, entity_type: str, host: str, fm_scheme: str, exp_result: str
):
    app.config["FLEXMEASURES_HOSTS_AND_AUTH_START"] = {
        "flexmeasures.io": "2021-01",
        "staging.flexmeasures.io": "2022-09",
    }
    if exp_result.startswith("ea1"):
        assert build_entity_address(info, entity_type, host, fm_scheme) == exp_result
    else:
        with pytest.raises(EntityAddressException, match=exp_result):
            build_entity_address(info, entity_type, host, fm_scheme) == exp_result


@pytest.mark.parametrize(
    "entity_type, entity_address, exp_result",
    [
        (
            "connection",
            "ea2.2018-06.localhost:40:30",
            "starts with 'ea1'",
        ),
        (
            "connection",
            "ea1.2018-RR.localhost:40:30",
            "date specification",
        ),
        (
            "weather_sensor",
            "ea1.2018-04.localhost:5000:40:30",
            "Could not parse",  # no sensor type (which starts with a letter)
        ),
        ("connection", "ea1:40", "a date spec"),  # trying only an asset ID
        (
            "connection",
            "ea1.2018-06.localhost:5000:40:30",
            dict(naming_authority="2018-06.localhost", owner_id=40, asset_id=30),
        ),
        (
            "connection",
            "ea1.2018-06.localhost:40",
            dict(naming_authority="2018-06.localhost", asset_id=40, owner_id=None),
        ),
        (
            "connection",
            "ea1.2018-06.io.flexmeasures:40:30",
            dict(naming_authority="2018-06.io.flexmeasures", owner_id=40, asset_id=30),
        ),
        (
            "weather_sensor",
            "ea1.2018-06.io.flexmeasures:temperature:-52:73.0",
            dict(
                naming_authority="2018-06.io.flexmeasures",
                weather_sensor_type_name="temperature",
                latitude=-52,
                longitude=73.0,
            ),
        ),
        (
            "market",
            "ea1.2018-06.io.flexmeasures:epex_da",
            dict(naming_authority="2018-06.io.flexmeasures", market_name="epex_da"),
        ),
        (
            "event",
            "ea1.2018-06.io.flexmeasures.staging:40:30:302:soc",
            dict(
                naming_authority="2018-06.io.flexmeasures.staging",
                owner_id=40,
                asset_id=30,
                event_type="soc",
                event_id=302,
            ),
        ),
        (
            "event",
            "ea1.2018-06.io.flexmeasures.staging:30:302:soc",
            dict(
                naming_authority="2018-06.io.flexmeasures.staging",
                asset_id=30,
                owner_id=None,
                event_type="soc",
                event_id=302,
            ),
        ),
        (
            "connection",
            "ea1.2018-06.io.flexmeasures.staging:fm1.30",
            dict(
                naming_authority="2018-06.io.flexmeasures.staging",
                asset_id=30,
                owner_id=None,
                event_type="connection",
            ),
        ),
    ],
)
def test_parse_entity_address(entity_type, entity_address, exp_result):
    if isinstance(exp_result, str):  # this means we expect an exception
        with pytest.raises(EntityAddressException, match=exp_result):
            parse_entity_address(
                entity_address, entity_type=entity_type, fm_scheme="fm0"
            )
    else:
        res = parse_entity_address(
            entity_address, entity_type=entity_type, fm_scheme="fm0"
        )
        assert res["scheme"] == "ea1"
        assert res["naming_authority"] == exp_result["naming_authority"]
        if entity_type in ("connection", "event"):
            for field in ("asset_id", "owner_id"):
                assert res[field] == exp_result[field]
        if entity_type == "market":
            assert res["market_name"] == exp_result["market_name"]
        if entity_type == "weather_sensor":
            for field in ("weather_sensor_type_name", "latitude", "longitude"):
                assert res[field] == exp_result[field]
        if entity_type == "event":
            for field in ("event_type", "event_id"):
                assert res[field] == exp_result[field]


def test_reverse_domain_name():
    assert reverse_domain_name("flexmeasures.io") == "io.flexmeasures"
    assert reverse_domain_name("company.flexmeasures.io") == "io.flexmeasures.company"
    assert (
        reverse_domain_name("staging.company.flexmeasures.org")
        == "org.flexmeasures.company.staging"
    )
    assert (
        reverse_domain_name("staging.company.flexmeasures.io:4500")
        == "io.flexmeasures.company.staging"
    )
    assert (
        reverse_domain_name("https://staging.company.flexmeasures.io:4500")
        == "io.flexmeasures.company.staging"
    )
    assert (
        reverse_domain_name("https://user:pass@staging.company.flexmeasures.io:4500")
        == "io.flexmeasures.company.staging"
    )
    assert reverse_domain_name("test.flexmeasures.co.uk") == "uk.co.flexmeasures.test"
    assert (
        reverse_domain_name("test.staging.flexmeasures.co.uk")
        == "uk.co.flexmeasures.staging.test"
    )


def test_build_ea_scheme_and_naming_authority(app):
    assert build_ea_scheme_and_naming_authority(
        "localhost:5000"
    ) == "ea1.%s.localhost" % get_first_day_of_next_month().strftime("%Y-%m")
    assert (
        build_ea_scheme_and_naming_authority("flexmeasures.io")
        == "ea1.2021-01.io.flexmeasures"
    )
    app.config["FLEXMEASURES_HOSTS_AND_AUTH_START"] = {
        "flexmeasures.io": "2021-01",
        "company.flexmeasures.io": "2020-04",
    }
    assert (
        build_ea_scheme_and_naming_authority("company.flexmeasures.io")
        == "ea1.2020-04.io.flexmeasures.company"
    )
    assert (
        build_ea_scheme_and_naming_authority("company.flexmeasures.io", "1999-12")
        == "ea1.1999-12.io.flexmeasures.company"
    )
    with pytest.raises(Exception, match="adhere to the format"):
        build_ea_scheme_and_naming_authority("company.flexmeasures.io", "1999--13")
    with pytest.raises(Exception, match="should be in the range"):
        build_ea_scheme_and_naming_authority("company.flexmeasures.io", "1999-13")
    with pytest.raises(Exception, match="when authority"):
        build_ea_scheme_and_naming_authority("company.notflexmeasures.io")
