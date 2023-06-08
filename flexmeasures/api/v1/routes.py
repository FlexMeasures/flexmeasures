from flexmeasures.api.common.utils.deprecation_utils import abort_with_sunset_info
from flexmeasures.api.v1 import flexmeasures_api as flexmeasures_api_v1

SUNSET_V1_INFO = dict(
    api_version_sunset="1.0",
    sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1.html",
    api_version_upgrade_to="3.0",
)


@flexmeasures_api_v1.route("/getMeterData", methods=["GET", "POST"])
def get_meter_data():
    abort_with_sunset_info(**SUNSET_V1_INFO)


@flexmeasures_api_v1.route("/postMeterData", methods=["POST"])
def post_meter_data():
    abort_with_sunset_info(**SUNSET_V1_INFO)


@flexmeasures_api_v1.route("/getService", methods=["GET"])
def get_service():
    abort_with_sunset_info(**SUNSET_V1_INFO)
