from flexmeasures.utils.coding_utils import deprecated
import warnings


def other_function():
    pass


def test_deprecated_decorator():

    # defining a function that is deprecated
    @deprecated(other_function)
    def deprecated_function():
        pass

    with warnings.catch_warnings(record=True) as w:
        # Cause all warnings to always be triggered.
        warnings.simplefilter("always")

        deprecated_function()  # calling a deprecated function

        assert len(w) == 1  # only 1 warning being printed
        assert issubclass(
            w[-1].category, FutureWarning
        )  # warning type is FutureWarning
        assert "flexmeasures.utils.tests.test_coding_utils:other_function" in str(
            w[-1].message
        )  # checking that the message is correct
