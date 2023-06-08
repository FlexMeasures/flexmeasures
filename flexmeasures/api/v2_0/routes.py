from flexmeasures.api.common.utils.deprecation_utils import abort_with_sunset_info
from flexmeasures.api.v2_0 import flexmeasures_api as flexmeasures_api_v2_0

SUNSET_V2_INFO = dict(
    api_version_sunset="2.0",
    sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v2_0.html",
    api_version_upgrade_to="3.0",
)


@flexmeasures_api_v2_0.route("/assets", methods=["GET"])
def get_assets():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/assets", methods=["POST"])
def post_assets():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["GET"])
def get_asset(id: int):
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["PATCH"])
def patch_asset(id: int):
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["DELETE"])
def delete_asset(id: int):
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/users", methods=["GET"])
def get_users():
    pass


@flexmeasures_api_v2_0.route("/user/<id>", methods=["GET"])
def get_user(id: int):
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/user/<id>", methods=["PATCH"])
def patch_user(id: int):
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/user/<id>/password-reset", methods=["PATCH"])
def reset_user_password(id: int):
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/getConnection", methods=["GET"])
def get_connection():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/postPriceData", methods=["POST"])
def post_price_data():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/getMeterData", methods=["GET"])
def get_meter_data():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/postMeterData", methods=["POST"])
def post_meter_data():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/getService", methods=["GET"])
def get_service():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/getDeviceMessage", methods=["GET"])
def get_device_message():
    abort_with_sunset_info(**SUNSET_V2_INFO)


@flexmeasures_api_v2_0.route("/postUdiEvent", methods=["POST"])
def post_udi_event():
    abort_with_sunset_info(**SUNSET_V2_INFO)
