from flexmeasures.api.v1_3 import flexmeasures_api as flexmeasures_api_v1_3


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
