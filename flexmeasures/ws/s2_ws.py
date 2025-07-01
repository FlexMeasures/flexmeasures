"""
Flask implementation of the S2 protocol WebSocket server.
"""

import asyncio
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
)
from s2python.communication.reception_status_awaiter import ReceptionStatusAwaiter
from s2python.message import S2Message
from s2python.s2_parser import S2Parser
from s2python.s2_validation_error import S2ValidationError
from flexmeasures.ws import sock

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("S2FlaskWSServer")


class MessageHandlers:
    """Class to manage message handlers for different message types."""

    handlers: Dict[Type[S2Message], Callable]

    def __init__(self) -> None:
        self.handlers = {}

    async def handle_message(
        self,
        server: "S2FlaskWSServer",
        msg: S2Message,
        websocket: Sock,
    ) -> None:
        """Handle the S2 message using the registered handler.
        Args:
            server: The server instance handling the message
            msg: The S2 message to handle
            websocket: The websocket connection to the client
        """
        handler = self.handlers.get(type(msg))
        if handler is not None:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(server, msg, websocket)
                else:

                    def do_message() -> None:
                        handler(server, msg, websocket)

                    eventloop = asyncio.get_event_loop()
                    await eventloop.run_in_executor(executor=None, func=do_message)
            except Exception:
                message_id = getattr(msg, "message_id", "N/A")
                logger.error(
                    "While processing message %s an unrecoverable error occurred.",
                    message_id,
                )
                logger.error("Error: %s", traceback.format_exc())
                await server.respond_with_reception_status(
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

    def register_handler(self, msg_type: Type[S2Message], handler: Callable[..., Any]) -> None:
        """Register a handler for a specific message type.
        Args:
            msg_type: The message type to handle
            handler: The handler function
        """
        self.handlers[msg_type] = handler


class S2FlaskWSServer:
    """Flask-based WebSocket server implementation for S2 protocol."""

    def __init__(
        self,
        role: EnergyManagementRole = EnergyManagementRole.CEM,
        ws_path: str = "/s2",
        app: Optional[Flask] = None,
        sock: Optional[Sock] = None,
    ) -> None:
        """Initialize the WebSocket server.
        Args:
            app: The Flask app to use
            sock: The Sock instance to use
            role: The role of this server (CEM or RM)
            ws_path: The path for the WebSocket endpoint.
        """

        self.role = role
        self.ws_path = ws_path

        self.app = app if app else Flask(__name__)
        self.sock = sock if sock else Sock(self.app)

        self._handlers = MessageHandlers()
        self.s2_parser = S2Parser()
        self._connections: Dict[str, Sock] = {}
        self.reception_status_awaiter = ReceptionStatusAwaiter()

        self._register_default_handlers()
        self.sock.route(self.ws_path)(self._ws_handler)

    def _register_default_handlers(self) -> None:
        """Register default message handlers."""
        self._handlers.register_handler(Handshake, self.handle_handshake)
        self._handlers.register_handler(HandshakeResponse, self.handle_handshake_response)
        self._handlers.register_handler(ReceptionStatus, self.handle_reception_status)

    def _ws_handler(self, ws: Sock) -> None:
        """
        Wrapper to run the async websocket handler from a synchronous context.
        This is required for Flask's development server. An ASGI server would
        be able to run the async handler directly.
        """
        try:
            self.app.logger.info("Received connection from client")
            asyncio.run(self._handle_websocket_connection(ws))
        except Exception as e:
            self.app.logger.error("Error in websocket handler: %s", e)

    async def _handle_websocket_connection(self, websocket: Sock) -> None:
        """Handle incoming WebSocket connections."""
        client_id = str(uuid.uuid4())
        self.app.logger.info("Client %s connected.", client_id)
        self._connections[client_id] = websocket

        try:
            while True:
                message = await websocket.receive()
                try:
                    s2_msg = self.s2_parser.parse_as_any_message(message)
                    if isinstance(s2_msg, ReceptionStatus):
                        await self.reception_status_awaiter.receive_reception_status(s2_msg)
                        continue
                except json.JSONDecodeError:
                    await self.respond_with_reception_status(
                        subject_message_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                        status=ReceptionStatusValues.INVALID_DATA,
                        diagnostic_label="Not valid json.",
                        websocket=websocket,
                    )
                    continue
                try:
                    await self._handlers.handle_message(self, s2_msg, websocket)
                except json.JSONDecodeError:
                    await self.respond_with_reception_status(
                        subject_message_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                        status=ReceptionStatusValues.INVALID_DATA,
                        diagnostic_label="Not valid json.",
                        websocket=websocket,
                    )
                except S2ValidationError as e:
                    json_msg = json.loads(message)
                    message_id = json_msg.get("message_id")
                    if message_id:
                        await self.respond_with_reception_status(
                            subject_message_id=message_id,
                            status=ReceptionStatusValues.INVALID_MESSAGE,
                            diagnostic_label=str(e),
                            websocket=websocket,
                        )
                    else:
                        await self.respond_with_reception_status(
                            subject_message_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                            status=ReceptionStatusValues.INVALID_DATA,
                            diagnostic_label="Message appears valid json but could not find a message_id field.",
                            websocket=websocket,
                        )
                except Exception as e:
                    self.app.logger.error("Error processing message: %s", str(e))
                    raise
        except ConnectionClosed:
            self.app.logger.info("Connection with client %s closed", client_id)
        finally:
            if client_id in self._connections:
                del self._connections[client_id]
            self.app.logger.info("Client %s disconnected", client_id)

    async def respond_with_reception_status(
        self,
        subject_message_id: uuid.UUID,
        status: ReceptionStatusValues,
        diagnostic_label: str,
        websocket: Sock,
    ) -> None:
        """Send a reception status response."""
        response = ReceptionStatus(
            subject_message_id=subject_message_id,
            status=status,
            diagnostic_label=diagnostic_label,
        )
        self.app.logger.info("Sending reception status %s for message %s", status, subject_message_id)
        try:
            await websocket.send(response.to_json())
        except ConnectionClosed:
            self.app.logger.warning("Connection closed while sending reception status")

    async def send_msg_and_await_reception_status_async(
        self,
        s2_msg: S2Message,
        websocket: Sock,
        timeout_reception_status: float = 20.0,
        raise_on_error: bool = True,
    ) -> ReceptionStatus:
        """Send a message and await a reception status."""
        await self._send_and_forget(s2_msg, websocket)
        message_id = getattr(s2_msg, "message_id", uuid.UUID("00000000-0000-0000-0000-000000000000"))
        try:
            await asyncio.wait_for(websocket.receive(), timeout=timeout_reception_status)
            # Assuming the response is the correct reception status
            return ReceptionStatus(
                subject_message_id=message_id,
                status=ReceptionStatusValues.OK,
                diagnostic_label="Reception status received.",
            )
        except asyncio.TimeoutError:
            if raise_on_error:
                raise TimeoutError(f"Did not receive a reception status on time for {message_id}")
            return ReceptionStatus(
                subject_message_id=message_id,
                status=ReceptionStatusValues.PERMANENT_ERROR,
                diagnostic_label="Timeout waiting for reception status.",
            )
        except ConnectionClosed:
            return ReceptionStatus(
                subject_message_id=message_id,
                status=ReceptionStatusValues.OK,
                diagnostic_label="Connection closed, assuming OK status.",
            )

    async def handle_handshake(self, _: "S2FlaskWSServer", message: S2Message, websocket: Sock) -> None:
        """Handle handshake messages."""
        if not isinstance(message, Handshake):
            return
        self.app.logger.info("Received Handshake: %s", message.to_json())
        handshake_response = HandshakeResponse(
            message_id=message.message_id,
            selected_protocol_version=(
                message.supported_protocol_versions[0] if message.supported_protocol_versions else "2.0.0"
            ),  # TODO: proper version negotiation
        )
        await self._send_and_forget(handshake_response, websocket)

        await self.respond_with_reception_status(
            subject_message_id=message.message_id,
            status=ReceptionStatusValues.OK,
            diagnostic_label="Handshake received",
            websocket=websocket,
        )

    async def handle_handshake_response(self, _: "S2FlaskWSServer", message: S2Message, websocket: Sock) -> None:
        """Handle handshake response messages."""
        if not isinstance(message, HandshakeResponse):
            return
        self.app.logger.debug("Received HandshakeResponse: %s", message.to_json())
        # Send ReceptionStatus (OK) for the HandshakeResponse message
        await self.respond_with_reception_status(
            subject_message_id=message.message_id,
            status=ReceptionStatusValues.OK,
            diagnostic_label="HandshakeResponse processed okay.",
            websocket=websocket,
        )

    async def handle_reception_status(self, _: "S2FlaskWSServer", message: S2Message, websocket: Sock) -> None:
        """Handle reception status messages."""
        if not isinstance(message, ReceptionStatus):
            return
        self.app.logger.info("Received ReceptionStatus in handle_reception_status: %s", message.to_json())

    async def _send_and_forget(self, s2_msg: S2Message, websocket: Sock) -> None:
        """Send a message and forget about it."""
        try:
            await websocket.send(s2_msg.to_json())
        except ConnectionClosed:
            self.app.logger.warning("Connection closed while sending message")

    async def send_select_control_type(self, control_type: ControlType, websocket: Sock) -> None:
        """Select the control type."""
        select_control_type = SelectControlType(message_id=uuid.uuid4(), control_type=control_type)
        await self._send_and_forget(select_control_type, websocket)
