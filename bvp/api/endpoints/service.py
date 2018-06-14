from typing import List
from flask_json import as_json

from bvp.api import bvp_api


@bvp_api.route('/api/getService', methods=["GET"])
@as_json
def get_service() -> dict:
    """
    Public endpoint to list services
    """

    # Todo: Check version

    response = {
        "type": 'GetServiceResponse',
        "services": [
            {
                "name": "getMeterData",
                "access": service_access("getMeterData"),
                "description": "Request meter reading."
            },
            {
                "name": "postMeterData",
                "access": service_access("postMeterData"),
                "description": "Send meter reading."
            },
            {
                "name": "postUdiEvent",
                "access": service_access("postUdiEvent"),
                "description": "Send a description of some flexible consumption or production process as a USEF Device "
                               "Interface (UDI) event, including device capabilities (control constraints)."
            },
            {
                "name": "getDeviceMessage",
                "access": service_access("getDeviceMessage"),
                "description": "Get an Active Demand & Supply (ADS) request for a certain type of control action, "
                               "including control set points."
            }
        ]
    }

    return response


def service_access(service: str) -> List[str]:
    """
    For a given USEF service name (API endpoint), returns a list of USEF roles that are allowed to access the service.
    Todo: should probably be moved to a config file or the db
    """
    access = {
        "getMeterData": ["aggregator", "supplier", "mdc", "prosumer", "esco"],
        "postMeterData": ["mdc", "prosumer", "esco"],
        "postUdiEvent": ["prosumer", "esco"],
        "getDeviceMessage": ["prosumer", "esco"]
    }
    return access[service]
