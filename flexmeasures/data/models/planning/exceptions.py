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

    pass
