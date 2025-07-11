from flask_classful import FlaskView, route
from flask_json import as_json
from webargs.flaskparser import use_args
from flexmeasures.data.schemas.s2_python import (
    PairingRequestSchema,
    ConnectionRequestSchema,
    S2Role,
    Deployment,
)


class PairingAPI(FlaskView):

    route_base = "/pairing"
    trailing_slash = False

    @route("", methods=["POST"])
    @use_args(
        PairingRequestSchema, location="json"
    )  # Use Marshmallow schema for validation
    @as_json
    def index(self, pairing_request):
        """
        Handle PairingRequest and return PairingResponse.
        """

        # Todo: Process the data from the request
        print("Received PairingRequest:", pairing_request)

        # Generate the server node description and request connection URI
        s2_server_node_id = "server-node-001"
        server_node_description = {
            "brand": "Brand-X",
            "logoUri": "http://example.com/logo.png",
            "type": "Server",
            "modelName": "Model-Y",
            "userDefinedName": "Server Node 001",
            "role": S2Role.CEM,
            "deployment": Deployment.WAN,
        }
        request_connection_uri = "wss://example.com/connect"  # Example URI

        # Creating PairingResponse using the data processed
        pairing_response = {
            "s2ServerNodeId": s2_server_node_id,
            "serverNodeDescription": server_node_description,
            "requestConnectionUri": request_connection_uri,
        }

        # Return the response (it will automatically be serialized using Marshmallow)
        return pairing_response


class ConnectionAPI(FlaskView):

    route_base = "connection"
    trailing_slash = False

    @route("", methods=["POST"])
    @use_args(
        ConnectionRequestSchema, location="json"
    )  # Use Marshmallow schema for validation
    @as_json
    def index(self, connection_request):
        """
        Handle ConnectionRequest and return ConnectionResponse.
        """

        # Todo: Process the data from the request
        print("Received ConnectionRequest:", connection_request)

        # Generate the connection response
        connection_response = connection_request

        # Return the response (it will automatically be serialized using Marshmallow)
        return connection_response
