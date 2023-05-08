from flexmeasures.api.v1_1 import flexmeasures_api as flexmeasures_api_v1_1


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
