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
    @use_args(PairingRequestSchema, location="json")
    @as_json
    def index(self, pairing_request):
        """
        Handle PairingRequest and return PairingResponse.

        This method processes the incoming pairing request, which includes the token, public key,
        encryption algorithm, client node ID, client node description, and supported protocols.
        After processing the data, it generates a `PairingResponse` with server node details and
        a connection URI for the client to use.

        Request Body:
            - `token` (str, required): The authentication token for the request.
            - `publicKey` (str, required): The public key of the client.
            - `encryptionAlgorithm` (str, required): The encryption algorithm to use (e.g., `RSA-OAEP-256`).
            - `s2ClientNodeId` (str, required): The ID of the client node.
            - `s2ClientNodeDescription` (object, required): Information about the client node (brand, logo, type, etc.).
            - `supportedProtocols` (list of str, required): A list of protocols supported by the client.

        Response:
            - `s2ServerNodeId` (str): The server node ID that the client should connect to.
            - `serverNodeDescription` (object): Details about the server node, such as brand, model, and role.
            - `requestConnectionUri` (str): The URI for the client to establish a WebSocket connection to the server.

        Example Request Body:
        ```json
        {
            "token": "example-token",
            "publicKey": "example-public-key",
            "encryptionAlgorithm": "RSA-OAEP-256",
            "s2ClientNodeId": "client-node-001",
            "s2ClientNodeDescription": {
                "brand": "Brand-X",
                "logoUri": "http://example.com/logo.png",
                "type": "Client",
                "modelName": "Model-Y",
                "userDefinedName": "Client Node 001",
                "role": "CEM",
                "deployment": "WAN"
            },
            "supportedProtocols": ["WebSocketSecure"]
        }
        ```

        Example Response Body:
        ```json
        {
            "requestConnectionUri": "wss://example.com/connect",
            "s2ServerNodeId": "server-node-001",
            "serverNodeDescription": {
                "brand": "Brand-X",
                "deployment": "WAN",
                "logoUri": "http://example.com/logo.png",
                "modelName": "Model-Y",
                "role": "CEM",
                "type": "Server",
                "userDefinedName": "Server Node 001"
            },
            "status": 200
        }
        ```

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
    """
    API endpoint to handle a connection request for pairing with a server.

    This endpoint accepts a `ConnectionRequest` in the body of a POST request, validates it using
    the `ConnectionRequestSchema` schema, processes the data, and returns a `ConnectionResponse`.

    """

    route_base = "connection"
    trailing_slash = False

    @route("", methods=["POST"])
    @use_args(ConnectionRequestSchema, location="json")
    @as_json
    def index(self, connection_request):
        """
        Handle ConnectionRequest and return ConnectionResponse.

        This method processes the incoming connection request, which includes the client node ID and
        the list of supported protocols. The processed data is returned as a response.

        Request Body:
            - `s2ClientNodeId`: str (required) - The ID of the client node initiating the connection.
            - `supportedProtocols`: list of str (required) - A list of supported protocols for the connection.

        Response:
            - The response is a JSON object containing the same fields as the request, which may later be
            extended based on the processing logic.

        Example Request Body:
        ```json
        {
            "s2ClientNodeId": "client-node-001",
            "supportedProtocols": ["WebSocketSecure"]
        }
        ```

        Example Response Body:
        ```json
        {
            "s2ClientNodeId": "client-node-001",
            "supportedProtocols": [
                "WebSocketSecure"
            ]
            "status": 200,
        }
        ```

        """

        # Todo: Process the data from the request
        print("Received ConnectionRequest:", connection_request)

        # Generate the connection response
        connection_response = connection_request

        return connection_response
