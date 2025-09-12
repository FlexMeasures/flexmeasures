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
from s2python.frbc import (
    FRBCSystemDescription,
    FRBCFillLevelTargetProfile,
    FRBCStorageStatus,
    FRBCActuatorStatus,
    FRBCInstruction,
)
from s2python.message import S2Message
from s2python.s2_parser import S2Parser
from s2python.s2_validation_error import S2ValidationError

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("S2FlaskWSServerSync")


class FRBCDeviceData:
    """Class to store FRBC device data received from Resource Manager."""

    def __init__(self):
        self.system_description: Optional[FRBCSystemDescription] = None
        self.fill_level_target_profile: Optional[FRBCFillLevelTargetProfile] = None
        self.storage_status: Optional[FRBCStorageStatus] = None
        self.actuator_status: Optional[FRBCActuatorStatus] = None
        self.resource_id: Optional[str] = None

    def is_complete(self) -> bool:
        """Check if we have received all necessary data to generate instructions."""
        return (
            self.system_description is not None
            and self.fill_level_target_profile is not None
            and self.storage_status is not None
            and self.actuator_status is not None
        )


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
        self._device_data: Dict[str, FRBCDeviceData] = (
            {}
        )  # Store device data by resource_id
        self._websocket_to_resource: Dict[Sock, str] = (
            {}
        )  # Map websocket to resource_id
        self._register_default_handlers()
        self.sock.route(self.ws_path)(self._ws_handler)

    def _register_default_handlers(self) -> None:
        self._handlers.register_handler(Handshake, self.handle_handshake)
        self._handlers.register_handler(ReceptionStatus, self.handle_reception_status)
        self._handlers.register_handler(
            ResourceManagerDetails, self.handle_ResourceManagerDetails
        )
        # Register FRBC message handlers
        self._handlers.register_handler(
            FRBCSystemDescription, self.handle_frbc_system_description
        )
        self._handlers.register_handler(
            FRBCFillLevelTargetProfile, self.handle_frbc_fill_level_target_profile
        )
        self._handlers.register_handler(
            FRBCStorageStatus, self.handle_frbc_storage_status
        )
        self._handlers.register_handler(
            FRBCActuatorStatus, self.handle_frbc_actuator_status
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
            # Clean up websocket to resource mapping and device states
            if websocket in self._websocket_to_resource:
                resource_id = self._websocket_to_resource[websocket]
                del self._websocket_to_resource[websocket]

                # Clean up device data
                if resource_id in self._device_data:
                    del self._device_data[resource_id]

                # Clean up device state from scheduler if available
                if (
                    hasattr(self, "s2_scheduler")
                    and self.s2_scheduler is not None
                    and hasattr(self.s2_scheduler, "remove_device_state")
                ):
                    self.s2_scheduler.remove_device_state(resource_id)

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

        # Store the resource_id from ResourceManagerDetails for device identification
        resource_id = str(message.resource_id)
        self._websocket_to_resource[websocket] = resource_id

        if resource_id not in self._device_data:
            self._device_data[resource_id] = FRBCDeviceData()
        self._device_data[resource_id].resource_id = resource_id

    def handle_frbc_system_description(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCSystemDescription):
            return
        self.app.logger.info("Received FRBCSystemDescription: %s", message.to_json())

        # Get resource_id from websocket mapping
        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        if resource_id not in self._device_data:
            self._device_data[resource_id] = FRBCDeviceData()

        self._device_data[resource_id].system_description = message
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_fill_level_target_profile(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCFillLevelTargetProfile):
            return
        self.app.logger.info(
            "Received FRBCFillLevelTargetProfile: %s", message.to_json()
        )

        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        if resource_id not in self._device_data:
            self._device_data[resource_id] = FRBCDeviceData()

        self._device_data[resource_id].fill_level_target_profile = message
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_storage_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCStorageStatus):
            return
        self.app.logger.info("Received FRBCStorageStatus: %s", message.to_json())

        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        if resource_id not in self._device_data:
            self._device_data[resource_id] = FRBCDeviceData()

        self._device_data[resource_id].storage_status = message
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_actuator_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCActuatorStatus):
            return
        self.app.logger.info("Received FRBCActuatorStatus: %s", message.to_json())

        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        if resource_id not in self._device_data:
            self._device_data[resource_id] = FRBCDeviceData()

        self._device_data[resource_id].actuator_status = message
        self._check_and_generate_instructions(resource_id, websocket)

    def _check_and_generate_instructions(
        self, resource_id: str, websocket: Sock
    ) -> None:
        """Check if we have all required data and generate instructions if so."""
        device_data = self._device_data.get(resource_id)
        for attr in (
            "system_description",
            "fill_level_target_profile",
            "storage_status",
            "actuator_status",
        ):
            self.app.logger.debug(
                f"✅ {attr}? Go flight!"
                if getattr(device_data, attr, None) is not None
                else f"❌ {attr}? Hold on.."
            )
        if device_data is None or not device_data.is_complete():
            self.app.logger.info(f"Waiting for more data from device {resource_id}")
            return

        self.app.logger.info(
            f"All data received for device {resource_id}, generating instructions"
        )

        try:
            # Use the S2Scheduler to create and store device state
            if hasattr(self, "s2_scheduler") and self.s2_scheduler is not None:
                # Create S2FrbcDeviceState from FRBC messages and store in scheduler
                self.s2_scheduler.frbc_device_data = device_data
                self.s2_scheduler.device_state = self.s2_scheduler.create_device_states_from_frbc_data(
                    # resource_id=resource_id,
                    # system_description=device_data.system_description,
                    # fill_level_target_profile=device_data.fill_level_target_profile,
                    # storage_status=device_data.storage_status,
                    # actuator_status=device_data.actuator_status,
                )

                # Generate instructions using the scheduler
                schedule_results = self.s2_scheduler.compute()

                # Send generated instructions
                for result in schedule_results:
                    if isinstance(result, FRBCInstruction):
                        self._send_and_forget(result, websocket)
                        self.app.logger.info(
                            f"Sent FRBC instruction: {result.to_json()}"
                        )
                    elif isinstance(result, dict) and "sensor" in result:
                        # TODO: save result["data"] to sensor if needed for FlexMeasures
                        pass
            else:
                # Scheduler not available - log warning and skip instruction generation
                self.app.logger.warning(
                    f"S2Scheduler not available for device {resource_id}, cannot generate instructions"
                )

        except Exception as e:
            self.app.logger.error(
                f"Error generating instructions for device {resource_id}: {e}"
            )
            import traceback

            self.app.logger.error(f"Traceback: {traceback.format_exc()}")
            # Continue processing other devices
