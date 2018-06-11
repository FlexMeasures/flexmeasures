import pytest

from bvp.app import create as create_app


@pytest.fixture(scope="session")
def app():
    test_app = create_app(env="testing")
    return test_app
