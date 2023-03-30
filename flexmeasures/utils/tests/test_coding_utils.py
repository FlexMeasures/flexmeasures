from flexmeasures.utils.coding_utils import deprecated


def other_function():
    pass


def test_deprecated_decorator(caplog, app):

    # defining a function that is deprecated
    @deprecated(other_function, "v14")
    def deprecated_function():
        pass

    caplog.clear()

    deprecated_function()  # calling a deprecated function
    print(caplog.records)
    assert len(caplog.records) == 1  # only 1 warning being printed

    assert "flexmeasures.utils.tests.test_coding_utils:other_function" in str(
        caplog.records[0].message
    )  # checking that the message is correct

    assert "v14" in str(
        caplog.records[0].message
    )  # checking that the message is correct
