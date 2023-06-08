from flask import abort

from flexmeasures.api.v2_0 import flexmeasures_api as flexmeasures_api_v2_0


@flexmeasures_api_v2_0.route("/assets", methods=["GET"])
def get_assets():
    abort(410)


@flexmeasures_api_v2_0.route("/assets", methods=["POST"])
def post_assets():
    abort(410)


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["GET"])
def get_asset(id: int):
    abort(410)


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["PATCH"])
def patch_asset(id: int):
    abort(410)


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["DELETE"])
def delete_asset(id: int):
    abort(410)


@flexmeasures_api_v2_0.route("/users", methods=["GET"])
def get_users():
    pass


@flexmeasures_api_v2_0.route("/user/<id>", methods=["GET"])
def get_user(id: int):
    abort(410)


@flexmeasures_api_v2_0.route("/user/<id>", methods=["PATCH"])
def patch_user(id: int):
    abort(410)


@flexmeasures_api_v2_0.route("/user/<id>/password-reset", methods=["PATCH"])
def reset_user_password(id: int):
    abort(410)


@flexmeasures_api_v2_0.route("/getConnection", methods=["GET"])
def get_connection():
    abort(410)


@flexmeasures_api_v2_0.route("/postPriceData", methods=["POST"])
def post_price_data():
    abort(410)


@flexmeasures_api_v2_0.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    abort(410)


@flexmeasures_api_v2_0.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    abort(410)


@flexmeasures_api_v2_0.route("/getMeterData", methods=["GET"])
def get_meter_data():
    abort(410)


@flexmeasures_api_v2_0.route("/postMeterData", methods=["POST"])
def post_meter_data():
    abort(410)


@flexmeasures_api_v2_0.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    abort(410)


@flexmeasures_api_v2_0.route("/getService", methods=["GET"])
def get_service():
    abort(410)


@flexmeasures_api_v2_0.route("/getDeviceMessage", methods=["GET"])
def get_device_message():
    abort(410)


@flexmeasures_api_v2_0.route("/postUdiEvent", methods=["POST"])
def post_udi_event():
    abort(410)
