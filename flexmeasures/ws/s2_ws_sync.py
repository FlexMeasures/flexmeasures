"""
Flask implementation of the S2 protocol WebSocket server (sync mode only).
"""

import json
import logging
import traceback
import uuid
from typing import Any, Callable, Dict, Optional, Type

from flask import Flask
from flask_sock import ConnectionClosed, Sock

from s2python.common import (
    ControlType,
    EnergyManagementRole,
    Handshake,
    HandshakeResponse,
    ReceptionStatus,
    ReceptionStatusValues,
    SelectControlType,
    ResourceManagerDetails,
)
from s2python.message import S2Message
from s2python.s2_parser import S2Parser
from s2python.s2_validation_error import S2ValidationError

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("S2FlaskWSServerSync")


class MessageHandlersSync:
    """Class to manage sync message handlers for different message types."""

    handlers: Dict[Type[S2Message], Callable]

    def __init__(self) -> None:
        self.handlers = {}

    def handle_message(
        self,
        server: "S2FlaskWSServerSync",
        msg: S2Message,
        websocket: Sock,
    ) -> None:
        """Handle the S2 message using the registered handler."""
        handler = self.handlers.get(type(msg))
        if handler is not None:
            try:
                handler(server, msg, websocket)
            except Exception:
                message_id = getattr(msg, "message_id", "N/A")
                logger.error(
                    "While processing message %s an unrecoverable error occurred.",
                    message_id,
                )
                logger.error("Error: %s", traceback.format_exc())
                server.respond_with_reception_status(
                    subject_message_id=getattr(
                        msg,
                        "message_id",
                        uuid.UUID("00000000-0000-0000-0000-000000000000"),
                    ),
                    status=ReceptionStatusValues.PERMANENT_ERROR,
                    diagnostic_label=f"While processing message {message_id} an unrecoverable error occurred.",
                    websocket=websocket,
                )
                raise
        else:
            logger.warning(
                "Received a message of type %s but no handler is registered. Ignoring the message.",
                type(msg),
            )

    def register_handler(
        self, msg_type: Type[S2Message], handler: Callable[..., Any]
    ) -> None:
        self.handlers[msg_type] = handler


class S2FlaskWSServerSync:
    """Flask-based WebSocket server implementation for S2 protocol (sync mode only)."""

    def __init__(
        self,
        role: EnergyManagementRole = EnergyManagementRole.CEM,
        ws_path: str = "/s2",
        app: Optional[Flask] = None,
        sock: Optional[Sock] = None,
    ) -> None:
        self.role = role
        self.ws_path = ws_path
        self.app = app if app else Flask(__name__)
        self.sock = sock if sock else Sock(self.app)
        self._handlers = MessageHandlersSync()
        self.s2_parser = S2Parser()
        self._connections: Dict[str, Sock] = {}
        self._register_default_handlers()
        self.sock.route(self.ws_path)(self._ws_handler)

    def _register_default_handlers(self) -> None:
        self._handlers.register_handler(Handshake, self.handle_handshake)
        self._handlers.register_handler(ReceptionStatus, self.handle_reception_status)
        self._handlers.register_handler(
            ResourceManagerDetails, self.handle_ResourceManagerDetails
        )

    def _ws_handler(self, ws: Sock) -> None:
        try:
            self.app.logger.info("Received connection from client")
            self._handle_websocket_connection(ws)
        except Exception as e:
            self.app.logger.error("Error in websocket handler: %s", e)

    def _handle_websocket_connection(self, websocket: Sock) -> None:
        client_id = str(uuid.uuid4())
        self.app.logger.info("Client %s connected (sync).", client_id)
        self._connections[client_id] = websocket
        try:
            while True:
                message = websocket.receive()
                try:
                    s2_msg = self.s2_parser.parse_as_any_message(message)
                    self.app.logger.info(
                        "Received message in _handle_websocket_connection: %s",
                        s2_msg.to_json(),
                    )
                except json.JSONDecodeError:
                    self.respond_with_reception_status(
                        subject_message_id=uuid.UUID(
                            "00000000-0000-0000-0000-000000000000"
                        ),
                        status=ReceptionStatusValues.INVALID_DATA,
                        diagnostic_label="Not valid json.",
                        websocket=websocket,
                    )
                    continue
                try:
                    if not isinstance(s2_msg, ReceptionStatus):

                        self.respond_with_reception_status(
                            subject_message_id=s2_msg.message_id,
                            status=ReceptionStatusValues.OK,
                            diagnostic_label="Message received.",
                            websocket=websocket,
                        )
                    self._handlers.handle_message(self, s2_msg, websocket)
                except json.JSONDecodeError:
                    self.respond_with_reception_status(
                        subject_message_id=uuid.UUID(
                            "00000000-0000-0000-0000-000000000000"
                        ),
                        status=ReceptionStatusValues.INVALID_DATA,
                        diagnostic_label="Not valid json.",
                        websocket=websocket,
                    )
                except S2ValidationError as e:
                    json_msg = json.loads(message)
                    message_id = json_msg.get("message_id")
                    if message_id:
                        self.respond_with_reception_status(
                            subject_message_id=message_id,
                            status=ReceptionStatusValues.INVALID_MESSAGE,
                            diagnostic_label=str(e),
                            websocket=websocket,
                        )
                    else:
                        self.respond_with_reception_status(
                            subject_message_id=uuid.UUID(
                                "00000000-0000-0000-0000-000000000000"
                            ),
                            status=ReceptionStatusValues.INVALID_DATA,
                            diagnostic_label="Message appears valid json but could not find a message_id field.",
                            websocket=websocket,
                        )
                except Exception as e:
                    self.app.logger.error("Error processing message: %s", str(e))
                    raise
        except ConnectionClosed:
            self.app.logger.info("Connection with client %s closed (sync)", client_id)
        finally:
            if client_id in self._connections:
                del self._connections[client_id]
            self.app.logger.info("Client %s disconnected (sync)", client_id)

    def respond_with_reception_status(
        self,
        subject_message_id: uuid.UUID,
        status: ReceptionStatusValues,
        diagnostic_label: str,
        websocket: Sock,
    ) -> None:
        response = ReceptionStatus(
            subject_message_id=subject_message_id,
            status=status,
            diagnostic_label=diagnostic_label,
        )
        self.app.logger.info(
            "Sending reception status %s for message %s (sync)",
            status,
            subject_message_id,
        )
        try:
            websocket.send(response.to_json())
        except ConnectionClosed:
            self.app.logger.warning(
                "Connection closed while sending reception status (sync)"
            )

    def _send_and_forget(self, s2_msg: S2Message, websocket: Sock) -> None:
        try:
            websocket.send(s2_msg.to_json())
        except ConnectionClosed:
            self.app.logger.warning("Connection closed while sending message (sync)")

    def handle_handshake(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, Handshake):
            return
        self.app.logger.info("Received Handshake (sync): %s", message.to_json())

        handshake_response = HandshakeResponse(
            message_id=message.message_id,
            selected_protocol_version="1.0.0",
        )
        self._send_and_forget(handshake_response, websocket)
        self.app.logger.info("HandshakeResponse sent (sync)")
        # If client is RM, send control type selection
        if hasattr(message, "role") and message.role == EnergyManagementRole.RM:
            self.app.logger.info("Sending control type selection (sync)")
            select_control_type = SelectControlType(
                message_id=uuid.uuid4(),
                control_type=ControlType.FILL_RATE_BASED_CONTROL,
            )
            self._send_and_forget(select_control_type, websocket)
            self.app.logger.info("SelectControlType sent (sync)")

    def handle_reception_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, ReceptionStatus):
            return
        self.app.logger.info("Received ReceptionStatus (sync): %s", message.to_json())

    def handle_ResourceManagerDetails(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, ResourceManagerDetails):
            return
        self.app.logger.info(
            "Received ResourceManagerDetails (sync): %s", message.to_json()
        )
