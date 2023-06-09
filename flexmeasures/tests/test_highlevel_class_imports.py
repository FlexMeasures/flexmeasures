import pytest


@pytest.mark.parametrize(
    "class_name",
    [
        "Account",
        "AccountRole",
        "Asset",
        "Sensor",
        "Source",
        "User",
    ],
)
def test_class_imports(class_name: str):
    """Make sure that plugins can import these classes as `from flexmeasures import <class_name>`."""
    import flexmeasures as fm

    assert hasattr(fm, class_name)
