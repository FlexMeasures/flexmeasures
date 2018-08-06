from typing import Union, Optional
from datetime import datetime, timedelta

from ts_forecasting_pipeline import (
    DBSeriesSpecs,
    ModelSpecs,
    ModelState,
    create_fitted_model,
    evaluate_models,
)
from ts_forecasting_pipeline.utils import day_lags

from bvp.data.models.assets import Asset, Power
from bvp.data.models.weather import Weather
from bvp.data.config import db


# always show plots live
plot_path = None


def model_48h_a(
    solar_asset: Asset,
    start_of_training: datetime,
    end_of_testing: datetime,
    query_until: Optional[datetime] = None,
    evaluate: bool = False,
    specs_only: bool = False,
) -> Union[ModelSpecs, ModelState]:
    """Return a ModelState of a fitted model (or only ModelSpecs), ready to predict from end_of_testing onwards.
    Caution: Might need to query data before start_of_training,
    e.g. for lags (see SeriesSpecs in the returned ModelSpecs).
    Evaluation (including plots) is optional.
    TODO: if this is being used only for training and then usage, the ratio should be passed in and possibly
    be only train and no test. (==1, test for problems).
    """

    # make sure we have enough data for lagging and/or rolling
    query_start: datetime = start_of_training - timedelta(days=7)
    query_end: datetime = end_of_testing
    if query_until is not None:
        query_end = query_until

    # TODO: this should be lagged by the transform function?
    regressor_specs = [
        DBSeriesSpecs(
            name="radiation_forecast_2days_l2",
            db_engine=db.engine,
            query=Weather.make_query(
                "total_radiation",
                query_window=(query_start, query_end),
                horizon_window=(None, timedelta(hours=0)),
                session=db.session,
            ),
        )
    ]
    outcome_var_spec = DBSeriesSpecs(
        name="solar_production",
        db_engine=db.engine,
        query=Power.make_query(
            solar_asset.name,
            query_window=(query_start, query_end),
            horizon_window=(None, timedelta(hours=0)),
            session=db.session,
        ),
    )

    specs = ModelSpecs(
        outcome_var=outcome_var_spec,
        model_type="OLS",
        lags=day_lags([2, 3, 4, 5, 6, 7]),
        regressors=regressor_specs,
        start_of_training=start_of_training,
        end_of_testing=end_of_testing,
        ratio_training_testing_data=14 / 15,
    )

    if specs_only:
        return specs
    else:
        # Create and train the model
        model = create_fitted_model(specs, "1.0")

        if evaluate:
            evaluate_models(m1=ModelState(model, specs), plot_path=plot_path)
            print("params: %s" % model.params)

        return ModelState(model, specs)


# return this model as the latest
latest = model_48h_a
