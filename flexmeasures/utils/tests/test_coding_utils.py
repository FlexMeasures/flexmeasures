from flexmeasures.utils.coding_utils import deprecated


def other_function():
    return 1


def test_deprecated_decorator(caplog, app):

    # defining a function that is deprecated
    @deprecated(other_function, "v14")
    def deprecated_function():
        return other_function()

    caplog.clear()

    value = deprecated_function()  # calling a deprecated function
    print(caplog.records)
    assert len(caplog.records) == 1  # only 1 warning being printed

    assert "flexmeasures.utils.tests.test_coding_utils:other_function" in str(
        caplog.records[0].message
    )  # checking that the message is correct

    assert "v14" in str(
        caplog.records[0].message
    )  # checking that the message is correct

    assert (
        value == 1
    )  # check that the decorator is returning the value of `other_function`
