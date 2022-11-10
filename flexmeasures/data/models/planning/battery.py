from flexmeasures.data.models.planning.storage import StorageScheduler


def schedule_battery(*args, **kwargs):
    import warnings

    warnings.warn(
        f"The schedule_battery method is deprecated and will be removed from flexmeasures in a future version. Replace with StorageScheduler().schedule to suppress this warning.",
        FutureWarning,
    )
    return StorageScheduler().schedule(*args, **kwargs)
