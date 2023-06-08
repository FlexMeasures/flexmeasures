from flexmeasures.api.common.utils.deprecation_utils import abort_with_sunset_info
from flexmeasures.api.v1_2 import flexmeasures_api as flexmeasures_api_v1_2

SUNSET_V1_2_INFO = dict(
    api_version_sunset="1.2",
    sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_2.html",
    api_version_upgrade_to="3.0",
)


@flexmeasures_api_v1_2.route("/getDeviceMessage", methods=["GET"])
def get_device_message():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/postUdiEvent", methods=["POST"])
def post_udi_event():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/getConnection", methods=["GET"])
def get_connection():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/postPriceData", methods=["POST"])
def post_price_data():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/getMeterData", methods=["GET"])
def get_meter_data():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/postMeterData", methods=["POST"])
def post_meter_data():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)


@flexmeasures_api_v1_2.route("/getService", methods=["GET"])
def get_service():
    abort_with_sunset_info(**SUNSET_V1_2_INFO)
