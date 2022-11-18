from flexmeasures.data.models.planning.storage import StorageScheduler


def schedule_charging_station(*args, **kwargs):
    import warnings

    warnings.warn(
        "The schedule_charging_station method is deprecated and will be removed from flexmeasures in a future version. Replace with StorageScheduler().schedule to suppress this warning.",
        FutureWarning,
    )
    return StorageScheduler().schedule(*args, **kwargs)
