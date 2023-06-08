from flexmeasures.api.sunset import (
    flexmeasures_api_v1,
    flexmeasures_api_v1_1,
    flexmeasures_api_v1_2,
    flexmeasures_api_v1_3,
    flexmeasures_api_v2_0,
)


@flexmeasures_api_v1.route("/getMeterData", methods=["GET", "POST"])
def get_meter_data():
    pass


@flexmeasures_api_v1.route("/postMeterData", methods=["POST"])
def post_meter_data():
    pass


@flexmeasures_api_v1.route("/getService", methods=["GET"])
def get_service():
    pass


@flexmeasures_api_v1_1.route("/getConnection", methods=["GET"])
def get_connection():
    pass


@flexmeasures_api_v1_1.route("/postPriceData", methods=["POST"])
def post_price_data():
    pass


@flexmeasures_api_v1_1.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    pass


@flexmeasures_api_v1_1.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    pass


@flexmeasures_api_v1_1.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    pass


@flexmeasures_api_v1_1.route("/getMeterData", methods=["GET"])
def get_meter_data():
    pass


@flexmeasures_api_v1_1.route("/postMeterData", methods=["POST"])
def post_meter_data():
    pass


@flexmeasures_api_v1_1.route("/getService", methods=["GET"])
def get_service():
    pass


@flexmeasures_api_v1_2.route("/getDeviceMessage", methods=["GET"])
def get_device_message():
    pass


@flexmeasures_api_v1_2.route("/postUdiEvent", methods=["POST"])
def post_udi_event():
    pass


@flexmeasures_api_v1_2.route("/getConnection", methods=["GET"])
def get_connection():
    pass


@flexmeasures_api_v1_2.route("/postPriceData", methods=["POST"])
def post_price_data():
    pass


@flexmeasures_api_v1_2.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    pass


@flexmeasures_api_v1_2.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    pass


@flexmeasures_api_v1_2.route("/getMeterData", methods=["GET"])
def get_meter_data():
    pass


@flexmeasures_api_v1_2.route("/postMeterData", methods=["POST"])
def post_meter_data():
    pass


@flexmeasures_api_v1_2.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    pass


@flexmeasures_api_v1_2.route("/getService", methods=["GET"])
def get_service():
    pass


@flexmeasures_api_v1_3.route("/getDeviceMessage", methods=["GET"])
def get_device_message():
    pass


@flexmeasures_api_v1_3.route("/postUdiEvent", methods=["POST"])
def post_udi_event():
    pass


@flexmeasures_api_v1_3.route("/getConnection", methods=["GET"])
def get_connection():
    pass


@flexmeasures_api_v1_3.route("/postPriceData", methods=["POST"])
def post_price_data():
    pass


@flexmeasures_api_v1_3.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    pass


@flexmeasures_api_v1_3.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    pass


@flexmeasures_api_v1_3.route("/getMeterData", methods=["GET"])
def get_meter_data():
    pass


@flexmeasures_api_v1_3.route("/postMeterData", methods=["POST"])
def post_meter_data():
    pass


@flexmeasures_api_v1_3.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    pass


@flexmeasures_api_v1_3.route("/getService", methods=["GET"])
def get_service():
    pass


@flexmeasures_api_v2_0.route("/assets", methods=["GET"])
def get_assets():
    pass


@flexmeasures_api_v2_0.route("/assets", methods=["POST"])
def post_assets():
    pass


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["GET"])
def get_asset(id: int):
    pass


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["PATCH"])
def patch_asset(id: int):
    pass


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["DELETE"])
def delete_asset(id: int):
    pass


@flexmeasures_api_v2_0.route("/users", methods=["GET"])
def get_users():
    pass


@flexmeasures_api_v2_0.route("/user/<id>", methods=["GET"])
def get_user(id: int):
    pass


@flexmeasures_api_v2_0.route("/user/<id>", methods=["PATCH"])
def patch_user(id: int):
    pass


@flexmeasures_api_v2_0.route("/user/<id>/password-reset", methods=["PATCH"])
def reset_user_password(id: int):
    pass


@flexmeasures_api_v2_0.route("/getConnection", methods=["GET"])
def get_connection():
    pass


@flexmeasures_api_v2_0.route("/postPriceData", methods=["POST"])
def post_price_data():
    pass


@flexmeasures_api_v2_0.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    pass


@flexmeasures_api_v2_0.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    pass


@flexmeasures_api_v2_0.route("/getMeterData", methods=["GET"])
def get_meter_data():
    pass


@flexmeasures_api_v2_0.route("/postMeterData", methods=["POST"])
def post_meter_data():
    pass


@flexmeasures_api_v2_0.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    pass


@flexmeasures_api_v2_0.route("/getService", methods=["GET"])
def get_service():
    pass


@flexmeasures_api_v2_0.route("/getDeviceMessage", methods=["GET"])
def get_device_message():
    pass


@flexmeasures_api_v2_0.route("/postUdiEvent", methods=["POST"])
def post_udi_event():
    pass
