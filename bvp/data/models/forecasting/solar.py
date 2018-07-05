from datetime import datetime, timedelta

import pytz
from ts_forecasting_pipeline import (
    DBSeriesSpecs,
    ModelSpecs,
    ModelState,
    create_fitted_model,
)
from ts_forecasting_pipeline.modelling import evaluate_models

from bvp.data.models.assets import Power
from bvp.data.models.weather import Weather
from bvp.data.config import db


plot_path = None


def day_lags(lags):
    return [l * 96 for l in lags]


def model1() -> ModelSpecs:
    start = (
        datetime(2015, 4, 13, 1, 45)
        .replace(tzinfo=pytz.utc)
        .astimezone(pytz.timezone("Asia/Seoul"))
    )
    end = start + timedelta(days=32)

    #  Getting data from DB - collect enough data for getting the lags in
    regressor_specs = [
        DBSeriesSpecs(
            name="radiation_forecast_2days_l2",
            db_engine=db.engine,
            query=Weather.make_query(
                "total_radiation",
                query_start=start - timedelta(days=7),
                query_end=end,
                session=db.session,
            ),
        )
    ]
    outcome_var_spec = DBSeriesSpecs(
        name="solar_production",
        db_engine=db.engine,
        query=Power.make_query(
            "ss_pv",
            query_start=start - timedelta(days=7),
            query_end=end,
            session=db.session,
        ),
    )

    specs = ModelSpecs(
        outcome_var=outcome_var_spec,
        model_type="OLS",
        lags=day_lags([2, 3, 4, 5, 6, 7]),
        regressors=regressor_specs,
        start_of_data=start,
        end_of_data=end,
        ratio_training_test_data=14 / 15,
    )

    # Create and train the model
    model = create_fitted_model(specs, "1.0")
    # Evaluate the model
    evaluate_models(m1=ModelState(model, specs), plot_path=plot_path)

    return model
