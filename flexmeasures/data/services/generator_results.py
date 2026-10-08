"""Checking and saving what a data generator returns, in one way for every kind of data generator.

A data generator, such as a scheduler, a reporter, a forecaster or a plugin's automation type,
returns its results as dicts naming the "sensor" to record on and holding the "data" to record there.
Whichever kind of generator it is, and whether it runs in a worker or from the CLI,
its results are checked against the sensors it may record on and saved the same way here.
"""

from __future__ import annotations

from collections.abc import Iterable

from flexmeasures.data import db
from flexmeasures.data.utils import save_to_db_and_count


class GeneratorWritesUncheckedSensor(Exception):
    """Raised when a data generator returns results for a sensor that nobody's permissions were checked against.

    It is a refusal rather than a passing failure: the same results are refused again on every retry,
    until the generator's configuration or the sensors it was checked against change.
    It derives from Exception rather than PermissionError,
    because PermissionError is the operating system's (an OSError), which the same jobs raise when they cannot write a file.
    The facts are kept as attributes, so that a handler need not read them from the message.
    """

    def __init__(
        self,
        generator: str,
        refused_sensor_ids: Iterable[int],
        permitted_sensor_ids: Iterable[int],
        automation_id: int | None = None,
    ):
        self.generator = generator
        self.refused_sensor_ids = sorted(set(refused_sensor_ids))
        self.permitted_sensor_ids = sorted(set(permitted_sensor_ids))
        self.automation_id = automation_id
        checked_against = (
            f"automation {automation_id} was checked against when it was created"
            if automation_id is not None
            else "it may record on"
        )
        super().__init__(
            f"{generator} would record data on sensor(s) {', '.join(str(i) for i in self.refused_sensor_ids)},"
            f" which are not among the sensors {checked_against}"
            f" ({', '.join(str(i) for i in self.permitted_sensor_ids) or 'none'})."
        )

    def __reduce__(self):
        """Rebuild the refusal from its fields, so that it survives pickling, as an RQ job's meta pickles it.

        Exception rebuilds an instance from its args, which hold only the message,
        and this constructor needs the fields, so without this an unpickled job meta would lose every key it holds.
        """
        return (
            type(self),
            (
                self.generator,
                self.refused_sensor_ids,
                self.permitted_sensor_ids,
                self.automation_id,
            ),
        )


def describe_generator(generator) -> str:
    """Name a data generator for a message: its class, and its data source if it already has one.

    The data source is only named when the generator already holds it, since asking for it could create one.
    """
    source = getattr(generator, "_data_source", None)
    if source is not None and source.id is not None:
        return f"{type(generator).__name__} (data source {source.id})"
    return type(generator).__name__


def check_generator_results(
    results: Iterable[dict],
    permitted_sensor_ids: set[int] | None,
    generator: str,
    automation_id: int | None = None,
) -> None:
    """Refuse results for any sensor outside the permitted ones, judging the whole set before any of it is saved or handed back.

    A result without a sensor, such as a scheduler's own bookkeeping, records on no sensor, so it is not judged.
    Pass None for permitted_sensor_ids where no such check applies, as on the CLI, whose user is trusted.

    :raises GeneratorWritesUncheckedSensor: naming the generator, the refused sensors and the permitted ones.
    """
    if permitted_sensor_ids is None:
        return
    refused = {
        result["sensor"].id
        for result in results
        if "sensor" in result and result["sensor"].id not in permitted_sensor_ids
    }
    if refused:
        raise GeneratorWritesUncheckedSensor(
            generator, refused, permitted_sensor_ids, automation_id
        )


def save_generator_results(results: Iterable[dict]) -> list[dict]:
    """Save what a data generator returns, all of it or none of it, and say how many beliefs each result saved.

    The results are saved within a savepoint, so a save that fails halfway leaves none of them staged,
    while whatever the caller staged before stays as it was.
    Committing is left to the caller, as it is for ``save_to_db``, so that the results can be part of a larger transaction.
    A belief that repeats the belief right before it is not saved again, as for any other data,
    which also makes saving results a generator already saved itself cost nothing extra.

    :returns: per result, the sensor id and the number of beliefs saved ("n_rows"),
        which leaves out NaN values and beliefs that were already on record.
    """
    saved = []
    with db.session.begin_nested():
        for result in results:
            _, n_saved = save_to_db_and_count(result["data"])
            saved.append({"sensor_id": result["sensor"].id, "n_rows": n_saved})
    return saved


def save_results_not_yet_saved(results: list[dict]) -> None:
    """Save the results that do not say how many of their beliefs were saved, and record that number on each of them as "n_saved".

    A generator that saves its results as it goes, such as the built-in forecasting pipeline, says so with "n_saved" on each result,
    and is not saved again.
    One that only returns its results has them saved here,
    and one that saved them itself anyway costs nothing extra, since its beliefs are then already on record.
    Committing is left to the caller.
    """
    unsaved = [result for result in results if "n_saved" not in result]
    if not unsaved:
        return
    for result, saved in zip(unsaved, save_generator_results(unsaved)):
        result["n_saved"] = saved["n_rows"]
