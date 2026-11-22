class MissingAttributeException(Exception):
    pass


class WrongEntityException(Exception):
    pass


class UnknownMarketException(Exception):
    pass


class UnknownForecastException(Exception):
    pass


class UnknownPricesException(Exception):
    pass


class WrongTypeAttributeException(Exception):
    pass


class InfeasibleProblemException(Exception):
    pass


class UpstreamSchedulingFailure(Exception):
    """A schedule could not be computed, because a scheduling job it depended on failed."""

    # This error only reports a failure that was recorded before, so it should not replace that failure as the error of an automation run.
    reports_an_earlier_failure = True
