"""
Flask implementation of the S2 protocol WebSocket server (sync mode only).
"""

import json
import logging
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Type, List

from flask import Flask
from flask_sock import ConnectionClosed, Sock

from flexmeasures import Account, Asset, AssetType, Sensor, User
from flexmeasures.data import db
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.utils import save_to_db
from flexmeasures.api.common.utils.validators import parse_duration
from flexmeasures.data.services.utils import get_or_create_model
from flexmeasures.utils.coding_utils import only_if_timer_due
from flexmeasures.utils.time_utils import server_now
from s2python.common import (
    ControlType,
    EnergyManagementRole,
    Handshake,
    HandshakeResponse,
    ReceptionStatus,
    ReceptionStatusValues,
    RevokableObjects,
    RevokeObject,
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
from s2python.version import S2_VERSION
from timely_beliefs import BeliefsDataFrame

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("S2FlaskWSServerSync")


class FRBCDeviceData:
    """Class to store FRBC device data received from Resource Manager."""

    def __init__(self):
        self.system_description: Optional[FRBCSystemDescription] = None
        self.fill_level_target_profile: Optional[FRBCFillLevelTargetProfile] = None
        self.storage_status: Optional[FRBCStorageStatus] = None
        self.actuator_statuses: Dict[str, FRBCActuatorStatus] = (
            {}
        )  # Changed to dict by actuator_id
        self.resource_id: Optional[str] = None
        self.instructions: Optional[List[FRBCInstruction]] = []

    def is_complete(self) -> bool:
        """Check if we have received all necessary data to generate instructions."""
        # Check basic required data
        if (
            self.system_description is None
            or self.fill_level_target_profile is None
            or self.storage_status is None
        ):
            return False

        # Check that we have actuator status for ALL actuators in system description
        if self.system_description.actuators:
            required_actuator_ids = {
                str(actuator.id) for actuator in self.system_description.actuators
            }
            received_actuator_ids = set(self.actuator_statuses.keys())
            return required_actuator_ids.issubset(received_actuator_ids)

        return True


class ConnectionState:
    """Class to track the state of each WebSocket connection for rate limiting."""

    def __init__(self):
        self.last_compute_time: Optional[datetime] = None
        self.resource_id: Optional[str] = None
        self.last_operation_mode: Optional[uuid.UUID] = None
        self.sent_instructions: List[FRBCInstruction] = (
            []
        )  # Store sent instructions for revocation

    def can_compute(self, replanning_frequency: timedelta) -> bool:
        """Check if enough time has passed since the last compute call."""
        if self.last_compute_time is None:
            return True
        return (
            datetime.now(timezone.utc) - self.last_compute_time >= replanning_frequency
        )

    def update_compute_time(self) -> None:
        """Update the last compute time to now."""
        self.last_compute_time = datetime.now(timezone.utc)


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
                logger.debug("Error: %s", traceback.format_exc())
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
                f"Ignoring message of type {type(msg)}; no handler is registered",
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
        self._connection_states: Dict[Sock, ConnectionState] = (
            {}
        )  # Track connection state for rate limiting
        self._register_default_handlers()
        self.sock.route(self.ws_path)(self._ws_handler)
        self.s2_scheduler = None
        self.account: Account | None = None
        self.user: User | None = None
        self._assets: Dict[str, Asset] = {}

        self._minimum_measurement_period: timedelta = timedelta(minutes=5)
        self._timers: dict[str, datetime] = dict()

    def _is_timer_due(self, name: str):
        now = datetime.now()
        due_time = self._timers.get(name, now - self._minimum_measurement_period)
        if due_time <= now:
            self._timers[name] = now + self._minimum_measurement_period
            return True
        else:
            self.app.logger.debug(
                f"Timer for {name} is not due until {self._timers[name]}"
            )
            return False

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
        self.app.logger.info(f"Client {client_id} connected (sync)")
        self._connections[client_id] = websocket
        # Initialize connection state for rate limiting
        self._connection_states[websocket] = ConnectionState()
        try:
            while True:
                message = websocket.receive()
                try:
                    s2_msg = self.s2_parser.parse_as_any_message(message)
                    self.app.logger.info(
                        f"Received {s2_msg.message_type} message from client"
                    )

                    # Don't log verbose messages
                    verbose_message_types = ["FRBC.UsageForecast"]
                    if s2_msg.message_type not in verbose_message_types:
                        self.app.logger.debug(s2_msg.to_json())
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

                    # Finalize transaction
                    try:
                        db.session.commit()
                    except Exception as exc:
                        self.app.logger.warning(
                            f"Session could not be committed to database: {str(exc)}"
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
            self.app.logger.info(f"Connection with client {client_id} closed (sync)")
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

            # Clean up connection state
            if websocket in self._connection_states:
                del self._connection_states[websocket]

            self.app.logger.info(f"Client {client_id} disconnected (sync)")

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
            f"Sending reception status {status} for message {subject_message_id} (sync)",
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

    def _revoke_previous_instructions(
        self, connection_state: ConnectionState, websocket: Sock
    ) -> None:
        """Revoke all previously sent instructions before sending new ones."""
        if not connection_state.sent_instructions:
            return

        self.app.logger.info(
            f"Revoking {len(connection_state.sent_instructions)} previous instructions"
        )

        for instruction in connection_state.sent_instructions:
            revoke_msg = RevokeObject(
                message_id=uuid.uuid4(),
                object_type=RevokableObjects.FRBC_Instruction,
                object_id=instruction.message_id,
            )
            self._send_and_forget(revoke_msg, websocket)
            self.app.logger.info(
                f"Sent RevokeObject for instruction {instruction.message_id}"
            )

        # Clear the list of sent instructions after revoking
        connection_state.sent_instructions.clear()

    def _filter_instructions_by_operation_mode(
        self, instructions: list, connection_state: ConnectionState
    ) -> list:
        """Filter instructions to only include those with different operation_mode than the previous instruction."""
        if not instructions:
            return instructions

        filtered = []
        last_operation_mode = connection_state.last_operation_mode

        for instruction in instructions:
            # Always include the first instruction if we haven't sent any before
            # or if the operation mode is different from the last sent instruction
            if (
                last_operation_mode is None
                or instruction.operation_mode != last_operation_mode
            ):
                filtered.append(instruction)
                last_operation_mode = instruction.operation_mode

        return filtered

    def handle_handshake(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, Handshake):
            return
        self.app.logger.info("Received Handshake (sync)")
        self.app.logger.debug(message.to_json())

        if S2_VERSION not in message.supported_protocol_versions:
            raise NotImplementedError(
                f"Server supported protocol {S2_VERSION} not supported by client. Client supports: message.supported_protocol_versions"
            )

        handshake_response = HandshakeResponse(
            message_id=uuid.uuid4(),
            selected_protocol_version=S2_VERSION,
        )
        self._send_and_forget(handshake_response, websocket)
        self.app.logger.info("HandshakeResponse sent (sync)")
        self.app.logger.debug(handshake_response)
        # If client is RM, send control type selection
        if hasattr(message, "role") and message.role == EnergyManagementRole.RM:
            self.app.logger.debug("Sending control type selection (sync)")
            select_control_type = SelectControlType(
                message_id=uuid.uuid4(),
                control_type=ControlType.FILL_RATE_BASED_CONTROL,
            )
            self._send_and_forget(select_control_type, websocket)
            self.app.logger.info("SelectControlType sent (sync)")
            self.app.logger.debug(select_control_type)

    def handle_reception_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, ReceptionStatus):
            return
        self.app.logger.debug(message.to_json())

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
        self.ensure_resource_is_registered(resource_id=resource_id)

        self._device_data[resource_id].system_description = message
        for actuator in message.actuators:
            self.ensure_actuator_is_registered(
                actuator_id=str(actuator.id), resource_id=resource_id
            )
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
        self.ensure_resource_is_registered(resource_id=resource_id)

        self._device_data[resource_id].fill_level_target_profile = message
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_storage_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCStorageStatus):
            return
        self.app.logger.info("Received FRBCStorageStatus: %s", message.to_json())

        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self.ensure_resource_is_registered(resource_id=resource_id)

        self._device_data[resource_id].storage_status = message
        self.save_fill_level(
            fill_level=message.present_fill_level,
            resource_id=resource_id,
        )
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_actuator_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCActuatorStatus):
            return
        self.app.logger.info("Received FRBCActuatorStatus: %s", message.to_json())

        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self.ensure_resource_is_registered(resource_id=resource_id)

        # Store actuator status by actuator_id to support multiple actuators
        self._device_data[resource_id].actuator_statuses[
            str(message.actuator_id)
        ] = message
        self._check_and_generate_instructions(resource_id, websocket)

    def ensure_resource_is_registered(self, resource_id: str):
        try:
            asset_type = get_or_create_model(AssetType, name="S2 Resource")
            self._assets[resource_id] = get_or_create_model(
                model_class=Asset,
                name=resource_id,
                account_id=self.account.id,
                generic_asset_type=asset_type,
            )
        except Exception as exc:
            self.app.logger.warning(
                f"Resource could not be saved as an asset: {str(exc)}"
            )
        if resource_id not in self._device_data:
            self._device_data[resource_id] = FRBCDeviceData()

    def ensure_actuator_is_registered(self, actuator_id: str, resource_id: str):
        try:
            asset_type = get_or_create_model(AssetType, name="S2 Actuator")
            self._assets[actuator_id] = get_or_create_model(
                model_class=Asset,
                name=actuator_id,
                account_id=self.account.id,
                generic_asset_type=asset_type,
                parent_asset=self._assets[resource_id],
            )
        except Exception as exc:
            self.app.logger.warning(
                f"Actuator could not be saved as an asset: {str(exc)}"
            )

    @only_if_timer_due("resource_id")
    def save_fill_level(self, resource_id: str, fill_level: float):
        try:
            asset = self._assets[resource_id]
            sensor = get_or_create_model(
                model_class=Sensor,
                name="fill level",
                unit="",
                event_resolution=timedelta(0),
                generic_asset=asset,
            )
            belief = TimedBelief(
                sensor=sensor,
                source=self.user.data_source,
                event_start=server_now(),
                event_value=fill_level,
                belief_horizon=timedelta(0),
                cumulative_probability=0.5,
            )
            bdf = BeliefsDataFrame(beliefs=[belief])
            save_to_db(bdf)

        except Exception as exc:
            self.app.logger.warning(
                f"Fill level could not be saved as sensor data: {str(exc)}"
            )

    def _check_and_generate_instructions(  # noqa: C901
        self, resource_id: str, websocket: Sock
    ) -> None:
        """Check if we have all required data and generate instructions if so."""
        device_data = self._device_data.get(resource_id)
        if device_data:
            # Debug log basic attributes
            for attr in (
                "system_description",
                "fill_level_target_profile",
                "storage_status",
            ):
                self.app.logger.debug(
                    f"✅ {attr}? Go flight!"
                    if getattr(device_data, attr, None) is not None
                    else f"❌ {attr}? Hold on.."
                )

            # Debug log actuator statuses
            if (
                device_data.system_description
                and device_data.system_description.actuators
            ):
                required_actuators = {
                    str(a.id) for a in device_data.system_description.actuators
                }
                received_actuators = set(device_data.actuator_statuses.keys())
                missing_actuators = required_actuators - received_actuators

                if missing_actuators:
                    self.app.logger.debug(
                        f"❌ actuator_status? Hold on.. Missing: {missing_actuators}"
                    )
                else:
                    self.app.logger.debug(
                        f"✅ actuator_status? Go flight! All {len(required_actuators)} actuators received"
                    )
        if device_data is None or not device_data.is_complete():
            self.app.logger.info(
                f"Waiting for more data from device {resource_id} before running the S2FlaskScheduler"
            )
            return

        # Check rate limiting based on FLEXMEASURES_S2_REPLANNING_FREQUENCY
        connection_state = self._connection_states.get(websocket)
        if connection_state is None:
            self.app.logger.warning(
                f"No connection state found for device {resource_id}"
            )
            return

        # Parse replanning frequency from config
        replanning_freq_str = self.app.config.get(
            "FLEXMEASURES_S2_REPLANNING_FREQUENCY", "PT5M"
        )
        try:
            replanning_frequency = parse_duration(replanning_freq_str)
            if replanning_frequency is None:
                raise ValueError(f"Invalid duration format: {replanning_freq_str}")
            if not isinstance(replanning_frequency, timedelta):
                # Handle isodate.Duration objects by converting to timedelta
                # For simplicity, assume it's a basic duration that can be converted
                replanning_frequency = timedelta(
                    seconds=replanning_frequency.total_seconds()
                )
        except Exception as e:
            self.app.logger.error(
                f"Error parsing FLEXMEASURES_S2_REPLANNING_FREQUENCY '{replanning_freq_str}': {e}"
            )
            replanning_frequency = timedelta(minutes=5)  # Default to 5 minutes

        # Check if we can compute based on rate limiting
        if not connection_state.can_compute(replanning_frequency):
            time_since_last = (
                datetime.now(timezone.utc) - connection_state.last_compute_time
            )
            remaining_time = replanning_frequency - time_since_last
            self.app.logger.info(
                f"Rate limiting: Cannot generate instructions for device {resource_id}. "
                f"Last compute was {time_since_last.total_seconds():.1f}s ago. "
                f"Need to wait {remaining_time.total_seconds():.1f}s more."
            )
            return

        self.app.logger.info(
            f"All data received for device {resource_id}, generating instructions"
        )

        try:
            # Use the S2FlaskScheduler to create and store device state
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

                # Update the compute time before calling the scheduler
                connection_state.update_compute_time()

                # Generate instructions using the scheduler
                schedule_results = self.s2_scheduler.compute()

                # Filter and send generated instructions
                frbc_instructions = [
                    result
                    for result in schedule_results
                    if isinstance(result, FRBCInstruction)
                ]
                filtered_instructions = self._filter_instructions_by_operation_mode(
                    frbc_instructions, connection_state
                )

                # Revoke previous instructions before sending new ones
                self._revoke_previous_instructions(connection_state, websocket)

                # Send new instructions and store them
                for instruction in filtered_instructions:
                    self._send_and_forget(instruction, websocket)
                    self.app.logger.info(
                        f"Sent FRBC instruction: {instruction.to_json()}"
                    )
                    # Update the last operation mode for this connection
                    connection_state.last_operation_mode = instruction.operation_mode

                # Store the sent instructions for future revocation
                connection_state.sent_instructions = filtered_instructions.copy()

                # Log filtering results
                if len(frbc_instructions) > len(filtered_instructions):
                    self.app.logger.info(
                        f"Filtered instructions: {len(frbc_instructions)} -> {len(filtered_instructions)} "
                        f"(reduced by {len(frbc_instructions) - len(filtered_instructions)})"
                    )

                # Process non-instruction results
                for result in schedule_results:
                    if isinstance(result, dict) and "sensor" in result:
                        # TODO: save result["data"] to sensor if needed for FlexMeasures
                        pass
            else:
                # Scheduler not available - log warning and skip instruction generation
                self.app.logger.warning(
                    f"S2FlaskScheduler not available for device {resource_id}, cannot generate instructions"
                )

        except Exception as e:
            self.app.logger.error(
                f"Error generating instructions for device {resource_id}: {e}"
            )
            import traceback

            self.app.logger.debug(f"Traceback: {traceback.format_exc()}")
            # Continue processing other devices
