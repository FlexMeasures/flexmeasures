from flexmeasures.app import create
from flexmeasures.api.v3_0 import create_openapi_specs


def main():
    app = create()
    create_openapi_specs(app)


if __name__ == "__main__":
    main()
