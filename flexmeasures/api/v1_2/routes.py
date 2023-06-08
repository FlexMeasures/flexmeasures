from flask import abort

from flexmeasures.api.v1_2 import flexmeasures_api as flexmeasures_api_v1_2


@flexmeasures_api_v1_2.route("/getDeviceMessage", methods=["GET"])
def get_device_message():
    abort(410)


@flexmeasures_api_v1_2.route("/postUdiEvent", methods=["POST"])
def post_udi_event():
    abort(410)


@flexmeasures_api_v1_2.route("/getConnection", methods=["GET"])
def get_connection():
    abort(410)


@flexmeasures_api_v1_2.route("/postPriceData", methods=["POST"])
def post_price_data():
    abort(410)


@flexmeasures_api_v1_2.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    abort(410)


@flexmeasures_api_v1_2.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    abort(410)


@flexmeasures_api_v1_2.route("/getMeterData", methods=["GET"])
def get_meter_data():
    abort(410)


@flexmeasures_api_v1_2.route("/postMeterData", methods=["POST"])
def post_meter_data():
    abort(410)


@flexmeasures_api_v1_2.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    abort(410)


@flexmeasures_api_v1_2.route("/getService", methods=["GET"])
def get_service():
    abort(410)
