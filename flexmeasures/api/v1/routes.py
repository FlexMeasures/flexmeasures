from flask import abort

from flexmeasures.api.v1 import flexmeasures_api as flexmeasures_api_v1


@flexmeasures_api_v1.route("/getMeterData", methods=["GET", "POST"])
def get_meter_data():
    abort(410)


@flexmeasures_api_v1.route("/postMeterData", methods=["POST"])
def post_meter_data():
    abort(410)


@flexmeasures_api_v1.route("/getService", methods=["GET"])
def get_service():
    abort(410)
