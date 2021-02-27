from flexmeasures.api.common.utils.api_utils import save_to_db

from datetime import timedelta

from flask import current_app
from flask_security import current_user

from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)
from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_horizon,
    invalid_unit,
    unrecognized_market,
)
from flexmeasures.api.common.utils.api_utils import (
    get_or_create_user_data_source,
)
from flexmeasures.api.common.utils.validators import (
    type_accepted,
    units_accepted,
    assets_required,
    post_data_checked_for_required_resolution,
    optional_horizon_accepted,
    optional_prior_accepted,
    period_required,
    values_required,
)
from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.services.forecasting import create_forecasting_jobs


@type_accepted("PostPriceDataRequest")
@units_accepted("price", "EUR/MWh", "KRW/kWh")
@assets_required("market")
@optional_horizon_accepted()
@optional_prior_accepted()
@values_required
@period_required
@post_data_checked_for_required_resolution("market")
def post_price_data_response(  # noqa C901
    unit,
    generic_asset_name_groups,
    horizon,
    prior,
    value_groups,
    start,
    duration,
    resolution,
):

    current_app.logger.info("POSTING PRICE DATA")

    data_source = get_or_create_user_data_source(current_user)
    prices = []
    forecasting_jobs = []
    for market_group, value_group in zip(generic_asset_name_groups, value_groups):
        for market in market_group:

            # Parse the entity address
            try:
                ea = parse_entity_address(market, entity_type="market")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            market_name = ea["market_name"]

            # Look for the Market object
            market = Market.query.filter(Market.name == market_name).one_or_none()
            if market is None:
                return unrecognized_market(market_name)
            elif unit != market.unit:
                return invalid_unit("%s prices" % market.display_name, [market.unit])

            # Create new Price objects
            resolution = duration / len(value_group)
            event_starts = [start + j * resolution for j in range(len(value_group))]
            event_values = [value for value in value_group]
            if horizon is not None and prior is not None:
                belief_horizons_from_horizon = [horizon] * len(value_group)
                belief_horizons_from_prior = [
                    event_start - prior - market.knowledge_horizon(event_start)
                    for event_start in event_starts
                ]
                belief_horizons = [
                    max(a, b)
                    for a, b in zip(
                        belief_horizons_from_horizon, belief_horizons_from_prior
                    )
                ]
            elif horizon is not None:
                belief_horizons = [horizon] * len(value_group)
            elif prior is not None:
                belief_horizons = [
                    event_start - prior - market.knowledge_horizon(event_start)
                    for event_start in event_starts
                ]
            else:
                extra_info = "Missing horizon or prior."
                return invalid_horizon(extra_info)
            prices.extend(
                [
                    Price(
                        datetime=event_start,
                        value=event_value,
                        horizon=belief_horizon,
                        market_id=market.id,
                        data_source_id=data_source.id,
                    )
                    for event_start, event_value, belief_horizon in zip(
                        event_starts, event_values, belief_horizons
                    )
                ]
            )

            # Make forecasts, but not in play mode. Price forecasts (horizon>0) can still lead to other price forecasts,
            # by the way, due to things like day-ahead markets.
            if current_app.config.get("FLEXMEASURES_MODE", "") != "play":
                # Forecast 24 and 48 hours ahead for at most the last 24 hours of posted price data
                forecasting_jobs = create_forecasting_jobs(
                    "Price",
                    market.id,
                    max(start, start + duration - timedelta(hours=24)),
                    start + duration,
                    resolution=duration / len(value_group),
                    horizons=[timedelta(hours=24), timedelta(hours=48)],
                    enqueue=False,  # will enqueue later, only if we successfully saved prices
                )

    return save_to_db(prices, forecasting_jobs)
