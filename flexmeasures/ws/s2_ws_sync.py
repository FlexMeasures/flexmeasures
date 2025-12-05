"""
Flask implementation of the S2 protocol WebSocket server (sync mode only).
"""

import json
import logging
import math
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Type, List

import pandas as pd
from flask import Flask
from flask_sock import ConnectionClosed, Sock

from flexmeasures import Account, Asset, AssetType, Sensor, Source, User
from flexmeasures.data import db
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.utils import save_to_db
from flexmeasures.api.common.utils.validators import parse_duration
from flexmeasures.data.services.utils import get_or_create_model
from flexmeasures.utils.coding_utils import only_if_timer_due
from flexmeasures.utils.flexmeasures_inflection import capitalize
from flexmeasures.utils.time_utils import floored_server_now, server_now
from flexmeasures.utils.unit_utils import convert_units
from s2python.common import (
    ControlType,
    EnergyManagementRole,
    Handshake,
    HandshakeResponse,
    InstructionStatus,
    InstructionStatusUpdate,
    PowerMeasurement,
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
    FRBCUsageForecast,
    FRBCLeakageBehaviour,
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
        self.usage_forecast: Optional[FRBCUsageForecast] = None
        self.leakage_behaviour: Optional[FRBCLeakageBehaviour] = None
        self.resource_id: Optional[str] = None
        self.instructions: Optional[List[FRBCInstruction]] = []
        self.logger = None

    def is_complete(self) -> bool:
        """Check if we have received all necessary data to generate instructions."""
        # System description and storage status are always required
        if self.system_description is None or self.storage_status is None:
            return False

        # Fill level target profile OR usage forecast should be provided (at least one)
        # Both are optional individually, but at least one should exist for meaningful planning
        has_fill_level_target = self.fill_level_target_profile is not None
        has_usage_forecast = self.usage_forecast is not None

        if not (has_fill_level_target or has_usage_forecast):
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
        self.instruction_statuses: Dict[uuid.UUID, InstructionStatus] = (
            {}
        )  # Track status of each instruction by instruction_id

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

    def update_instruction_status(
        self, instruction_id: uuid.UUID, status: InstructionStatus
    ) -> None:
        """Update the status of an instruction."""
        self.instruction_statuses[instruction_id] = status


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
                    status=ReceptionStatusValues.TEMPORARY_ERROR,
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
        self.data_source_id: int | None = None
        self._assets: Dict[str, Asset] = {}

        self._minimum_measurement_period: timedelta = timedelta(minutes=5)
        self._timers: dict[str, datetime] = dict()

    def _is_timer_due(self, name: str) -> bool:
        now = datetime.now()
        due_time = self._timers.get(name, now - self._minimum_measurement_period)
        if due_time <= now:
            # Get total seconds of the period
            period_seconds = self._minimum_measurement_period.total_seconds()

            # Seconds since start of the hour
            seconds_since_hour = now.minute * 60 + now.second + now.microsecond / 1e6

            # Ceil to next multiple of period_seconds
            next_tick_seconds = (
                math.ceil(seconds_since_hour / period_seconds) * period_seconds
            )

            # Compute next due datetime
            next_due = now.replace(minute=0, second=0, microsecond=0) + timedelta(
                seconds=next_tick_seconds
            )
            self._timers[name] = next_due
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
        self._handlers.register_handler(
            InstructionStatusUpdate, self.handle_instruction_status_update
        )
        self._handlers.register_handler(PowerMeasurement, self.handle_power_measurement)
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
        self._handlers.register_handler(
            FRBCUsageForecast, self.handle_frbc_usage_forecast
        )
        self._handlers.register_handler(
            FRBCLeakageBehaviour, self.handle_frbc_leakage_behaviour
        )

    def _ws_handler(self, ws: Sock) -> None:
        try:
            self.app.logger.info("🔌 New WebSocket connection received")
            self._handle_websocket_connection(ws)
        except Exception as e:
            self.app.logger.error("❌ WebSocket handler error: %s", e)

    def _handle_websocket_connection(self, websocket: Sock) -> None:
        client_id = str(uuid.uuid4())
        self.app.logger.info(f" Client connected: {client_id[:8]}...")
        self._connections[client_id] = websocket
        # Initialize connection state for rate limiting
        self._connection_states[websocket] = ConnectionState()
        try:
            while True:
                message = websocket.receive()
                s2_msg = None
                try:
                    s2_msg = self.s2_parser.parse_as_any_message(message)

                    # Log with appropriate emoji based on message type
                    msg_emoji = {
                        "Handshake": "🤝",
                        "FRBC.SystemDescription": "📋",
                        "FRBC.FillLevelTargetProfile": "🎯",
                        "FRBC.StorageStatus": "🔋",
                        "FRBC.ActuatorStatus": "⚙️",
                        "FRBC.UsageForecast": "💧",
                        "FRBC.LeakageBehaviour": "🔄",
                        "InstructionStatusUpdate": "📊",
                        "ResourceManagerDetails": "📝",
                        "PowerMeasurement": "⚡",
                    }.get(s2_msg.message_type, "📥")

                    self.app.logger.info(f"{msg_emoji} {s2_msg.message_type}")

                    # Don't log verbose message content
                    verbose_message_types = [
                        "FRBC.UsageForecast",
                        "FRBC.ActuatorStatus",
                    ]
                    if s2_msg.message_type not in verbose_message_types:
                        self.app.logger.debug(s2_msg.to_json())
                except json.JSONDecodeError:
                    self.app.logger.warning(f"❌ Invalid JSON from client {client_id}")
                    self.respond_with_reception_status(
                        subject_message_id=uuid.UUID(
                            "00000000-0000-0000-0000-000000000000"
                        ),
                        status=ReceptionStatusValues.INVALID_DATA,
                        diagnostic_label="Not valid json.",
                        websocket=websocket,
                    )
                    continue
                except S2ValidationError as e:
                    self.app.logger.warning(
                        f"❌ S2 validation error from client {client_id}: {str(e)}"
                    )
                    try:
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

                # Handle valid message
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
                        self.app.logger.warning(f"⚠️ DB commit failed: {str(exc)}")
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
                    self.app.logger.error(
                        f"💥 Error processing message from client {client_id}: {str(e)}"
                    )
                    raise
        except ConnectionClosed:
            self.app.logger.info(f"🔌 Connection closed: {client_id[:8]}...")
        finally:
            if client_id in self._connections:
                del self._connections[client_id]
            # Clean up websocket to resource mapping and device states
            if websocket in self._websocket_to_resource:
                resource_id = self._websocket_to_resource[websocket]
                del self._websocket_to_resource[websocket]
                self.app.logger.debug(
                    f"🧹 Cleaned up resource mapping for {resource_id}"
                )

                # Clean up device data
                if resource_id in self._device_data:
                    del self._device_data[resource_id]
                    self.app.logger.debug(
                        f"🧹 Cleaned up device data for {resource_id}"
                    )

                # Clean up device state from scheduler if available
                if (
                    hasattr(self, "s2_scheduler")
                    and self.s2_scheduler is not None
                    and hasattr(self.s2_scheduler, "remove_device_state")
                ):
                    self.s2_scheduler.remove_device_state(resource_id)
                    self.app.logger.debug(
                        f"🧹 Cleaned up scheduler state for {resource_id}"
                    )

            # Clean up connection state
            if websocket in self._connection_states:
                del self._connection_states[websocket]

            self.app.logger.info(f"🚪 Client disconnected: {client_id[:8]}...")

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
        status_emoji = "✅" if status == ReceptionStatusValues.OK else "❌"
        self._logger(websocket).debug(f"{status_emoji} ReceptionStatus: {status}")
        try:
            websocket.send(response.to_json())
        except ConnectionClosed:
            self._logger(websocket).warning("⚠️ Connection closed during response")

    def _send_and_forget(self, s2_msg: S2Message, websocket: Sock) -> None:
        try:
            websocket.send(s2_msg.to_json())
        except ConnectionClosed:
            self._logger(websocket).warning("⚠️ Connection closed during send")

    def _revoke_previous_instructions(
        self, connection_state: ConnectionState, websocket: Sock
    ) -> None:
        """Revoke all previously sent instructions that are still ACCEPTED or NEW before sending new ones."""
        if not connection_state.sent_instructions:
            return

        # Filter instructions to only revoke those with ACCEPTED or NEW status
        # Instructions with other statuses have already been removed from memory
        instructions_to_revoke = [
            instr
            for instr in connection_state.sent_instructions
            if connection_state.instruction_statuses.get(
                instr.message_id, InstructionStatus.NEW
            )
            in (InstructionStatus.NEW, InstructionStatus.ACCEPTED)
        ]

        self._logger(websocket).info(
            f"🗑️ Revoking {len(instructions_to_revoke)}/{len(connection_state.sent_instructions)} instructions"
        )

        for instruction in instructions_to_revoke:
            revoke_msg = RevokeObject(
                message_id=uuid.uuid4(),
                object_type=RevokableObjects.FRBC_Instruction,
                object_id=instruction.id,
            )
            self._send_and_forget(revoke_msg, websocket)
            status = connection_state.instruction_statuses.get(
                instruction.message_id, InstructionStatus.NEW
            )
            self._logger(websocket).debug(
                f"   🚫 Revoked instruction {str(instruction.id)[:8]}... ({status.value})"
            )

        # Clear the list of sent instructions after revoking
        connection_state.sent_instructions.clear()

    def _filter_instructions_by_operation_mode(
        self, instructions: list, connection_state: ConnectionState, websocket: Sock
    ) -> list:
        """Filter instructions to only include those with different operation_mode than the previous instruction."""
        if not instructions:
            return instructions

        filtered = []
        last_operation_mode = connection_state.last_operation_mode
        skipped = 0

        for instruction in instructions:
            # Always include the first instruction if we haven't sent any before
            # or if the operation mode is different from the last sent instruction
            if (
                last_operation_mode is None
                or instruction.operation_mode != last_operation_mode
            ):
                filtered.append(instruction)
                last_operation_mode = instruction.operation_mode
            else:
                skipped += 1
        if skipped > 0:
            self._logger(websocket).info(
                f"🔽 Filtered: {len(instructions)} → {len(filtered)} instructions (skipped {skipped} duplicate modes)"
            )

        return filtered

    def handle_handshake(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, Handshake):
            return
        self.app.logger.debug(message.to_json())

        if S2_VERSION not in message.supported_protocol_versions:
            raise NotImplementedError(
                f"Server protocol {S2_VERSION} not supported by client"
            )

        handshake_response = HandshakeResponse(
            message_id=uuid.uuid4(),
            selected_protocol_version=S2_VERSION,
        )
        self._send_and_forget(handshake_response, websocket)
        self.app.logger.info(f"🤝 Handshake complete (protocol {S2_VERSION})")

        # If client is RM, send control type selection
        if hasattr(message, "role") and message.role == EnergyManagementRole.RM:
            select_control_type = SelectControlType(
                message_id=uuid.uuid4(),
                control_type=ControlType.FILL_RATE_BASED_CONTROL,
            )
            self._send_and_forget(select_control_type, websocket)
            self._logger(websocket).info("📤 SelectControlType: FRBC")

    def handle_reception_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, ReceptionStatus):
            return
        self._logger(websocket).debug(message.to_json())

    def handle_ResourceManagerDetails(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, ResourceManagerDetails):
            return

        # Store the resource_id from ResourceManagerDetails for device identification
        resource_id = str(message.resource_id)
        self._websocket_to_resource[websocket] = resource_id

        if resource_id not in self._device_data:
            self._device_data[resource_id] = FRBCDeviceData()

        dd = self._device_data[resource_id]
        dd.resource_id = resource_id

        # Create namespaced logger
        # safe name (no spaces/slashes etc)
        rm_name = str(message.name).replace(" ", "_")
        dd.logger = logging.getLogger(f"flexmeasures_s2.rm.{rm_name}")

        # Inherit app logger handlers/level
        dd.logger.setLevel(self.app.logger.level)

        self.app.logger.info(f"📝 RM registered: {resource_id[:8]}... ({message.name})")
        dd.logger.info("RM logger initialized")

    def handle_instruction_status_update(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, InstructionStatusUpdate):
            return

        # Get the connection state and update instruction status
        connection_state = self._connection_states.get(websocket)
        if connection_state:
            connection_state.update_instruction_status(
                message.instruction_id, message.status_type
            )

            # Status emoji mapping
            status_emoji = {
                InstructionStatus.NEW: "🆕",
                InstructionStatus.ACCEPTED: "✅",
                InstructionStatus.REJECTED: "❌",
                InstructionStatus.STARTED: "▶️",
                InstructionStatus.SUCCEEDED: "🎉",
                InstructionStatus.ABORTED: "⛔",
                InstructionStatus.REVOKED: "🚫",
            }.get(message.status_type, "📊")

            instr_id_full = str(message.instruction_id)
            instr_id_short = instr_id_full[:8]
            self._logger(websocket).info(
                f"{status_emoji} Instruction {instr_id_short}... → {message.status_type.value}"
            )
            self._logger(websocket).debug(f"   📋 Full instruction ID: {instr_id_full}")

            # If instruction is rejected, aborted, or revoked, remove it from sent_instructions
            if message.status_type not in (
                InstructionStatus.NEW,
                InstructionStatus.ACCEPTED,
            ):
                # Remove the instruction from sent_instructions list
                connection_state.sent_instructions = [
                    instr
                    for instr in connection_state.sent_instructions
                    if instr.message_id != message.instruction_id
                ]
                self._logger(websocket).debug(
                    f"   🗑️ Removed {instr_id_short}... from memory"
                )

    def handle_frbc_system_description(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCSystemDescription):
            return

        # Get resource_id from websocket mapping
        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self.ensure_resource_is_registered(resource_id=resource_id)

        self._device_data[resource_id].system_description = message
        n_actuators = len(message.actuators) if message.actuators else 0

        # Log details about actuators
        for actuator in message.actuators:
            n_modes = len(actuator.operation_modes) if actuator.operation_modes else 0
            n_transitions = len(actuator.transitions) if actuator.transitions else 0
            n_timers = len(actuator.timers) if actuator.timers else 0
            self._logger(websocket).debug(
                f"   ⚙️ Actuator {str(actuator.id)[:8]}...: {n_modes} modes, {n_transitions} transitions, {n_timers} timers"
            )
            self.ensure_actuator_is_registered(
                actuator_id=str(actuator.id), resource_id=resource_id
            )
            self.ensure_actuator_is_registered(
                actuator_id=str(actuator.id), resource_id=resource_id
            )

        # Log storage details
        if message.storage:
            self._logger(websocket).debug(
                f"   💾 Storage: {message.storage.fill_level_range.start_of_range}-{message.storage.fill_level_range.end_of_range} {message.storage.fill_level_label or '%'}"
            )

        self.save_attribute(resource_id, **json.loads(message.to_json()))
        self._logger(websocket).info(f"📋 SystemDescription: {n_actuators} actuator(s)")
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_fill_level_target_profile(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCFillLevelTargetProfile):
            return
        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self._logger(websocket).info(
            f"🎯 Received FRBCFillLevelTargetProfile for {resource_id}"
        )
        self._logger(websocket).debug(message.to_json())

        self.ensure_resource_is_registered(resource_id=resource_id)

        self._device_data[resource_id].fill_level_target_profile = message
        n_elements = len(message.elements) if message.elements else 0

        # Log target profile details
        if message.elements:
            try:
                # Duration objects have a value in milliseconds
                total_duration_ms = sum(int(elem.duration) for elem in message.elements)
                total_duration_min = total_duration_ms / 60000
                self._logger(websocket).debug(
                    f"   🎯 Total duration: {total_duration_min:.0f} min, Start: {message.start_time.strftime('%H:%M:%S')}"
                )
            except Exception as e:
                self._logger(websocket).debug(
                    f"   🎯 Start: {message.start_time.strftime('%H:%M:%S')}"
                )

        self._logger(websocket).info(f"🎯 TargetProfile: {n_elements} element(s)")
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_power_measurement(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, PowerMeasurement):
            return

        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self.ensure_resource_is_registered(resource_id=resource_id)

        power_measurements = message.values
        for measurement in power_measurements:
            try:
                self.save_event(
                    sensor_name=measurement.commodity_quantity,
                    event_value=measurement.value,
                    event_start=message.measurement_timestamp,
                    data_source_id=self.data_source_id,
                    resource_or_actuator_id=resource_id,
                )
            except Exception as exc:
                self._logger(websocket).warning(
                    f"PowerMeasurement could not be saved: {str(exc)}"
                )

    def handle_frbc_storage_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCStorageStatus):
            return
        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self._logger(websocket).info(f"🔋 Received FRBCStorageStatus for {resource_id}")
        self._logger(websocket).debug(message.to_json())

        self.ensure_resource_is_registered(resource_id=resource_id)

        self._device_data[resource_id].storage_status = message
        self.save_event(
            sensor_name="fill level",
            event_value=message.present_fill_level,
            data_source_id=self.data_source_id,
            resource_or_actuator_id=resource_id,
        )
        self._logger(websocket).info(
            f"🔋 StorageStatus: {message.present_fill_level:.1f}%"
        )
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_actuator_status(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCActuatorStatus):
            return
        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self._logger(websocket).info(
            f"⚙️ Received FRBCActuatorStatus for {resource_id} (actuator: {message.actuator_id})"
        )
        self._logger(websocket).debug(message.to_json())

        self.ensure_resource_is_registered(resource_id=resource_id)

        # Store actuator status by actuator_id to support multiple actuators
        self._device_data[resource_id].actuator_statuses[
            str(message.actuator_id)
        ] = message
        self._logger(websocket).debug(
            f"⚙️ ActuatorStatus: factor={message.operation_mode_factor}"
        )
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_usage_forecast(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCUsageForecast):
            return

        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self.ensure_resource_is_registered(resource_id=resource_id)

        self._device_data[resource_id].usage_forecast = message
        n_elements = len(message.elements) if message.elements else 0

        # Log usage forecast details
        if message.elements:
            try:
                # Duration objects have a value in milliseconds
                total_duration_ms = sum(int(elem.duration) for elem in message.elements)
                total_duration_min = total_duration_ms / 60000
                self._logger(websocket).debug(
                    f"   💧 Total duration: {total_duration_min:.0f} min, Start: {message.start_time.strftime('%H:%M:%S')}"
                )
            except Exception as e:
                self._logger(websocket).debug(
                    f"   💧 Start: {message.start_time.strftime('%H:%M:%S')}"
                )

        self._logger(websocket).info(f"💧 UsageForecast: {n_elements} element(s)")
        self._check_and_generate_instructions(resource_id, websocket)

    def handle_frbc_leakage_behaviour(
        self, _: "S2FlaskWSServerSync", message: S2Message, websocket: Sock
    ) -> None:
        if not isinstance(message, FRBCLeakageBehaviour):
            return

        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        self.ensure_resource_is_registered(resource_id=resource_id)

        self._device_data[resource_id].leakage_behaviour = message
        n_elements = len(message.elements) if message.elements else 0

        # Log leakage behaviour details
        if message.elements:
            try:
                # Log first element's leakage rate as example
                first_elem = message.elements[0]
                leakage_rate = first_elem.leakage_rate
                fill_range = first_elem.fill_level_range
                self._logger(websocket).debug(
                    f"   🔄 Leakage rate: {leakage_rate}, Fill range: {fill_range.start_of_range}-{fill_range.end_of_range}"
                )
            except Exception:
                pass

        self._logger(websocket).info(f"🔄 LeakageBehaviour: {n_elements} element(s)")
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

    def save_attribute(self, resource_id: str, **kwargs):
        asset = self._assets[resource_id]
        for k, v in kwargs.items():
            try:
                asset.attributes[k] = v
            except Exception as exc:
                self.app.logger.warning(
                    f"Failed to save {k}: {v} as an asset attribute of {asset}: {str(exc)}"
                )

    @only_if_timer_due("sensor_name", "resource_or_actuator_id", "data_source_id")
    def save_event(
        self,
        sensor_name: str,
        resource_or_actuator_id: str,
        event_value: float | pd.Series,
        data_source_id: int,
        event_start: str | None = None,
        event_resolution: timedelta | None = None,
        event_unit: str = "",
        sensor_unit: str = "",
    ):
        if event_resolution is None:
            event_resolution = timedelta(0)
        try:
            asset = self._assets[resource_or_actuator_id]
            sensor = get_or_create_model(
                model_class=Sensor,
                name=sensor_name,
                unit=sensor_unit,
                event_resolution=event_resolution,
                timezone=self.app.config["FLEXMEASURES_TIMEZONE"],
                generic_asset=asset,
            )
        except Exception as exc:
            self.app.logger.warning(
                f"{capitalize(sensor_name)} sensor could not be saved: {str(exc)}"
            )
            return
        try:
            event_value = convert_units(
                event_value,
                event_unit,
                sensor_unit,
                event_resolution=self.s2_scheduler.resolution,
            )
            try:
                data_source = db.session.get(Source, data_source_id)
            except Exception as exc:
                self.app.logger.warning(
                    f"Data source {data_source_id} could not be freshly fetched: {str(exc)}"
                )
            if isinstance(event_value, float):
                belief = TimedBelief(
                    sensor=sensor,
                    source=data_source,
                    event_start=event_start
                    or floored_server_now(self._minimum_measurement_period),
                    event_value=event_value,
                    belief_time=server_now(),
                    cumulative_probability=0.5,
                )
                bdf = BeliefsDataFrame(beliefs=[belief])
            elif isinstance(event_value, pd.Series):
                bdf = BeliefsDataFrame(
                    event_value,
                    sensor=sensor,
                    source=data_source,
                    belief_time=server_now(),
                    cumulative_probability=0.5,
                )
            else:
                logger.error(f"Cannot save event values of type {type(event_value)}.")
                return
            save_to_db(bdf)
            self.app.logger.debug(
                f"✅ {capitalize(sensor_name)} saved successfully: {bdf}"
            )

        except Exception as exc:
            self.app.logger.warning(
                f"{capitalize(sensor_name)} could not be saved as sensor data: {str(exc)}"
            )

    def _logger(self, websocket: Sock) -> logging.Logger:
        """Get the logger associated with the resource ID, or the app logger otherwise."""
        resource_id = self._websocket_to_resource.get(websocket, "default_resource")
        dd: str | None = self._device_data.get(resource_id)
        if hasattr(dd, "logger"):
            lgr = dd.logger
        else:
            lgr = self.app.logger
        return lgr

    def _check_and_generate_instructions(
        self, resource_id: str, websocket: Sock
    ) -> None:  # noqa: C901
        """Check if we have all required data and generate instructions if so."""
        device_data = self._device_data.get(resource_id)
        if device_data:
            # Build detailed status about what's missing
            missing_items = []

            if not device_data.system_description:
                missing_items.append("❌ SystemDescription")
            else:
                missing_items.append("✅ SystemDescription")

            if not device_data.fill_level_target_profile:
                missing_items.append("❌ FillLevelTargetProfile")
            else:
                missing_items.append("✅ FillLevelTargetProfile")

            if not device_data.usage_forecast:
                missing_items.append("❌ UsageForecast")
            else:
                missing_items.append("✅ UsageForecast")

            if not device_data.leakage_behaviour:
                missing_items.append("❌ LeakageBehaviour")
            else:
                missing_items.append("✅ LeakageBehaviour")

            if not device_data.storage_status:
                missing_items.append("❌ StorageStatus")
            else:
                missing_items.append("✅ StorageStatus")

            # Check actuator statuses in detail
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
                    missing_items.append(
                        f"❌ ActuatorStatus ({len(received_actuators)}/{len(required_actuators)} received)"
                    )
                    for missing_id in missing_actuators:
                        self._logger(websocket).debug(
                            f"   ⏳ Missing actuator status for: {missing_id}"
                        )
                else:
                    missing_items.append(
                        f"✅ ActuatorStatus (all {len(required_actuators)} received)"
                    )
            else:
                missing_items.append("❌ ActuatorStatus (no actuators defined)")

            # Log the status
            status_summary = " | ".join(missing_items)
            self._logger(websocket).debug(f"📊 Device readiness: {status_summary}")

        if device_data is None or not device_data.is_complete():
            # Log what's still missing
            if device_data is None:
                self._logger(websocket).info(
                    f"⏳ No device data yet for {resource_id[:8]}..."
                )
            else:
                missing = []
                if not device_data.system_description:
                    missing.append("SystemDescription")
                if (
                    not device_data.fill_level_target_profile
                    and not device_data.usage_forecast
                ):
                    missing.append("FillLevelTargetProfile or UsageForecast")
                if not device_data.storage_status:
                    missing.append("StorageStatus")
                if (
                    device_data.system_description
                    and device_data.system_description.actuators
                ):
                    required = {
                        str(a.id) for a in device_data.system_description.actuators
                    }
                    received = set(device_data.actuator_statuses.keys())
                    if required - received:
                        missing.append("ActuatorStatus")

                self._logger(websocket).info(f"⏳ Waiting for: {', '.join(missing)}")
            return

        # Check rate limiting based on FLEXMEASURES_S2_REPLANNING_FREQUENCY
        connection_state = self._connection_states.get(websocket)
        if connection_state is None:
            self._logger(websocket).warning(
                f"⚠️ No connection state for {resource_id[:8]}..."
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
                f"❌ Error parsing FLEXMEASURES_S2_REPLANNING_FREQUENCY '{replanning_freq_str}': {e}"
            )
            replanning_frequency = timedelta(minutes=5)  # Default to 5 minutes

        # Check if we can compute based on rate limiting
        if not connection_state.can_compute(replanning_frequency):
            time_since_last = (
                datetime.now(timezone.utc) - connection_state.last_compute_time
            )
            remaining_time = replanning_frequency - time_since_last
            self._logger(websocket).debug(
                f"⏱️ Rate limit: wait {remaining_time.total_seconds():.0f}s (last: {time_since_last.total_seconds():.0f}s ago)"
            )
            return

        self._logger(websocket).info(
            f"🎯 Generating instructions for {resource_id[:8]}..."
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

                # Recalculate scheduler start time: 15 minutes from now, aligned to 5-minute boundary
                now = datetime.now(timezone.utc)
                future_time = now + timedelta(minutes=15)
                minutes_offset = future_time.minute % 5
                start_aligned = future_time.replace(
                    minute=future_time.minute - minutes_offset, second=0, microsecond=0
                )

                # Update scheduler time window
                self.s2_scheduler.start = start_aligned
                self.s2_scheduler.end = start_aligned + timedelta(
                    hours=24
                )  # 24-hour planning window
                self.s2_scheduler.belief_time = start_aligned

                self._logger(websocket).debug(
                    f"🕐 Scheduler window: {self.s2_scheduler.start.strftime('%Y-%m-%d %H:%M:%S')} → {self.s2_scheduler.end.strftime('%Y-%m-%d %H:%M:%S')}"
                )

                # Generate instructions using the scheduler (this may query the database for costs)
                schedule_results = self.s2_scheduler.compute()

                # Filter and send generated instructions
                frbc_instructions = [
                    result
                    for result in schedule_results
                    if isinstance(result, FRBCInstruction)
                ]
                filtered_instructions = self._filter_instructions_by_operation_mode(
                    frbc_instructions, connection_state, websocket
                )

                # Revoke previous instructions before sending new ones
                self._revoke_previous_instructions(connection_state, websocket)

                # Log instruction summary before sending
                if filtered_instructions:
                    self._logger(websocket).info(
                        f"📤 Sending {len(filtered_instructions)} instruction(s):"
                    )

                # Send new instructions and store them
                current_time = datetime.now(timezone.utc)
                for idx, instruction in enumerate(filtered_instructions, 1):
                    self._send_and_forget(instruction, websocket)

                    # Full IDs
                    instr_id_full = str(instruction.message_id)
                    mode_id_full = str(instruction.operation_mode)
                    actuator_id_full = str(instruction.actuator_id)

                    # Short IDs for compact display
                    instr_id_short = instr_id_full[:8]
                    mode_id_short = mode_id_full[:8]
                    actuator_short = actuator_id_full[:8]

                    exec_time = (
                        instruction.execution_time.strftime("%H:%M:%S")
                        if hasattr(instruction.execution_time, "strftime")
                        else str(instruction.execution_time)
                    )
                    factor = instruction.operation_mode_factor

                    # Validate that execution time is in the future
                    if hasattr(instruction.execution_time, "tzinfo"):
                        exec_datetime = instruction.execution_time
                        time_until_exec = (exec_datetime - current_time).total_seconds()
                        if time_until_exec < 0:
                            self._logger(websocket).warning(
                                f"   ⚠️ Instruction {instr_id_short}... has execution time {time_until_exec:.0f}s in the PAST!"
                            )
                        elif time_until_exec < 60:
                            self._logger(websocket).warning(
                                f"   ⚠️ Instruction {instr_id_short}... executes in only {time_until_exec:.0f}s (might be too soon)"
                            )

                    # Log with short IDs for readability
                    self._logger(websocket).info(
                        f"   {idx}. {instr_id_short}... | mode: {mode_id_short}... | factor: {factor:.2f} | actuator: {actuator_short}... | exec: {exec_time}"
                    )

                    # Log full IDs at debug level
                    self._logger(websocket).debug(
                        f"      📋 Full instruction ID: {instr_id_full}"
                    )
                    self._logger(websocket).debug(
                        f"      🔧 Full operation mode ID: {mode_id_full}"
                    )
                    self._logger(websocket).debug(
                        f"      ⚙️  Full actuator ID: {actuator_id_full}"
                    )

                    # Update the last operation mode for this connection
                    connection_state.last_operation_mode = instruction.operation_mode

                # Store the sent instructions for future revocation
                connection_state.sent_instructions = filtered_instructions.copy()

                # Process non-instruction results
                try:
                    energy_data_count = 0
                    for result in schedule_results:
                        if isinstance(result, dict) and "device" in result:
                            energy_data_count += 1
                            device_short = str(result["device"])[:8]
                            if isinstance(result.get("data"), pd.Series):
                                n_values = len(result["data"])
                                self._logger(websocket).debug(
                                    f"   💾 Saving {n_values} energy values for device {device_short}... ({result.get('unit', '?')})"
                                )
                            self.save_event(
                                sensor_name="power",
                                resource_or_actuator_id=str(result["device"]),
                                event_value=result["data"],
                                data_source_id=self.s2_scheduler.data_source.id,
                                event_resolution=self.s2_scheduler.resolution,
                                event_unit=result["unit"],
                                sensor_unit="W",
                            )
                        if isinstance(result, dict) and "fill level" in result:
                            self._logger(websocket).debug(f"Saving result: {result}")
                            self.save_event(
                                sensor_name="fill level",
                                resource_or_actuator_id=str(result["fill level"]),
                                event_value=result["data"],
                                data_source_id=self.s2_scheduler.data_source.id,
                            )
                    if energy_data_count > 0:
                        self._logger(websocket).info(
                            f"💾 Saved energy data for {energy_data_count} device(s)"
                        )
                except Exception as exc:
                    self._logger(websocket).warning(
                        f"⚠️ Energy data save failed: {str(exc)}"
                    )
            else:
                # Scheduler not available - log warning and skip instruction generation
                self.app.logger.warning(
                    f"⚠️ S2FlaskScheduler not available for {resource_id}"
                )

        except Exception as e:
            self.app.logger.error(
                f"💥 Error generating instructions for {resource_id}: {e}"
            )
            import traceback

            self.app.logger.debug(f"Traceback: {traceback.format_exc()}")
            # Continue processing other devices
