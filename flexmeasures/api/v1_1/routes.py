from flask import abort

from flexmeasures.api.v1_1 import flexmeasures_api as flexmeasures_api_v1_1


@flexmeasures_api_v1_1.route("/getConnection", methods=["GET"])
def get_connection():
    abort(410)


@flexmeasures_api_v1_1.route("/postPriceData", methods=["POST"])
def post_price_data():
    abort(410)


@flexmeasures_api_v1_1.route("/postWeatherData", methods=["POST"])
def post_weather_data():
    abort(410)


@flexmeasures_api_v1_1.route("/getPrognosis", methods=["GET"])
def get_prognosis():
    abort(410)


@flexmeasures_api_v1_1.route("/postPrognosis", methods=["POST"])
def post_prognosis():
    abort(410)


@flexmeasures_api_v1_1.route("/getMeterData", methods=["GET"])
def get_meter_data():
    abort(410)


@flexmeasures_api_v1_1.route("/postMeterData", methods=["POST"])
def post_meter_data():
    abort(410)


@flexmeasures_api_v1_1.route("/getService", methods=["GET"])
def get_service():
    abort(410)
