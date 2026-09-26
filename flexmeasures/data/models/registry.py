"""The Schedulers, Reporters and Forecasters that FlexMeasures ships with, and that a user can select by name.

Listed explicitly rather than found by walking ``flexmeasures.data.models``, which imported every module under it at start-up.
Adding a built-in data generator means adding a line here; a test checks this list against a full walk, so a forgotten line fails.
Entries are written as ``"dotted.module.path:ClassName"``, as strings, because naming the modules directly would import them circularly.
"""

from __future__ import annotations

#: Maps a data generator type to the built-in implementations of that type.
#: The keys are the keys of ``app.data_generators``.
BUILTIN_DATA_GENERATORS: dict[str, list[str]] = {
    "forecaster": [
        "flexmeasures.data.models.forecasting.pipelines.train_predict:TrainPredictPipeline",
    ],
    "reporter": [
        "flexmeasures.data.models.reporting.aggregator:AggregatorReporter",
        "flexmeasures.data.models.reporting.pandas_reporter:PandasReporter",
        "flexmeasures.data.models.reporting.profit:ProfitOrLossReporter",
    ],
    "scheduler": [
        "flexmeasures.data.models.planning.process:ProcessScheduler",
        "flexmeasures.data.models.planning.storage:StorageScheduler",
    ],
}
