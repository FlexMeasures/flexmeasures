import pandas as pd
import models
from fbprophet import Prophet


# Maybe we want to make a model separately
# def make_model_for(data: pd.Series):
#    return data


def make_rolling_forecast(data: pd.Series, asset_type: models.AssetType) -> pd.DataFrame:
    """Return a df with three series, forecast from the data: yhat, yhat_upper and yhat_lower
    (naming follows convention, e.g. from Prophet).
    It will be indexed the same way as the given data series.
    """

    # Rename the datetime and data column for use in fbprophet
    df = pd.DataFrame({'ds': data.index, 'y': data.values})

    # Precondition the model to look for certain trends and seasonalities, and fit it
    model = Prophet(interval_width=models.confidence_interval_width, **asset_type.preconditions)
    model.fit(df)

    # Select some window and resolution for the forecast
    start_ = model.history_dates.min()
    end_ = model.history_dates.max()
    dates = pd.date_range(start=start_, end=end_, freq=data.index.freq)
    window = pd.DataFrame({'ds': dates})

    # Cheap rolling horizon forecast
    forecast = model.predict(window)

    # Put only the confidence intervals for the forecast in a separate df
    confidence_df = pd.DataFrame(index=data.index, columns=["yhat", "yhat_upper", "yhat_lower"])
    confidence_df["yhat_upper"] = forecast.yhat_upper.values
    confidence_df["yhat"] = forecast.yhat.values
    confidence_df["yhat_lower"] = forecast.yhat_lower.values

    return confidence_df
