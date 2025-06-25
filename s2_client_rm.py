import argparse
import logging
import threading
import datetime
import uuid
from typing import Callable

from s2python.authorization.default_client import S2DefaultClient
from s2python.generated.gen_s2_pairing import (
    S2NodeDescription,
    Deployment,
    PairingToken,
    S2Role,
    Protocols,
)

from s2python.common import (
    EnergyManagementRole,
    Duration,
    Role,
    RoleType,
    Commodity,
    Currency,
    NumberRange,
    PowerRange,
    CommodityQuantity,
)
from s2python.frbc import (
    FRBCInstruction,
    FRBCSystemDescription,
    FRBCActuatorDescription,
    FRBCStorageDescription,
    FRBCOperationMode,
    FRBCOperationModeElement,
    FRBCFillLevelTargetProfile,
    FRBCFillLevelTargetProfileElement,
    FRBCStorageStatus,
    FRBCActuatorStatus,
)
from s2python.communication.s2_connection import S2Connection, AssetDetails
from s2python.s2_control_type import FRBCControlType, NoControlControlType
from s2python.message import S2Message

logger = logging.getLogger("s2python")


class MyFRBCControlType(FRBCControlType):
    def handle_instruction(self, conn: S2Connection, msg: S2Message, send_okay: Callable[[], None]) -> None:
        if not isinstance(msg, FRBCInstruction):
            raise RuntimeError(f"Expected an FRBCInstruction but received a message of type {type(msg)}.")
        print(f"I have received the message {msg} from {conn}")

    def activate(self, conn: S2Connection) -> None:
        print("The control type FRBC is now activated.")

        print("Time to send a FRBC SystemDescription")
        actuator_id = uuid.uuid4()
        operation_mode_id = uuid.uuid4()
        conn.send_msg_and_await_reception_status_sync(
            FRBCSystemDescription(
                message_id=uuid.uuid4(),
                valid_from=datetime.datetime.now(tz=datetime.timezone.utc),
                actuators=[
                    FRBCActuatorDescription(
                        id=actuator_id,
                        operation_modes=[
                            FRBCOperationMode(
                                id=operation_mode_id,
                                elements=[
                                    FRBCOperationModeElement(
                                        fill_level_range=NumberRange(start_of_range=0.0, end_of_range=100.0),
                                        fill_rate=NumberRange(start_of_range=-5.0, end_of_range=5.0),
                                        power_ranges=[
                                            PowerRange(
                                                start_of_range=-200.0,
                                                end_of_range=200.0,
                                                commodity_quantity=CommodityQuantity.ELECTRIC_POWER_L1,
                                            )
                                        ],
                                    )
                                ],
                                diagnostic_label="Load & unload battery",
                                abnormal_condition_only=False,
                            )
                        ],
                        transitions=[],
                        timers=[],
                        supported_commodities=[Commodity.ELECTRICITY],
                    )
                ],
                storage=FRBCStorageDescription(
                    fill_level_range=NumberRange(start_of_range=0.0, end_of_range=100.0),
                    fill_level_label="%",
                    diagnostic_label="Imaginary battery",
                    provides_fill_level_target_profile=True,
                    provides_leakage_behaviour=False,
                    provides_usage_forecast=False,
                ),
            )
        )
        print("Also send the target profile")

        conn.send_msg_and_await_reception_status_sync(
            FRBCFillLevelTargetProfile(
                message_id=uuid.uuid4(),
                start_time=datetime.datetime.now(tz=datetime.timezone.utc),
                elements=[
                    FRBCFillLevelTargetProfileElement(
                        duration=Duration.from_milliseconds(30_000),
                        fill_level_range=NumberRange(start_of_range=20.0, end_of_range=30.0),
                    ),
                    FRBCFillLevelTargetProfileElement(
                        duration=Duration.from_milliseconds(300_000),
                        fill_level_range=NumberRange(start_of_range=40.0, end_of_range=50.0),
                    ),
                ],
            )
        )

        print("Also send the storage status.")
        conn.send_msg_and_await_reception_status_sync(
            FRBCStorageStatus(message_id=uuid.uuid4(), present_fill_level=10.0)
        )

        print("Also send the actuator status.")
        conn.send_msg_and_await_reception_status_sync(
            FRBCActuatorStatus(
                message_id=uuid.uuid4(),
                actuator_id=actuator_id,
                active_operation_mode_id=operation_mode_id,
                operation_mode_factor=0.5,
            )
        )

    def deactivate(self, conn: S2Connection) -> None:
        print("The control type FRBC is now deactivated.")


class MyNoControlControlType(NoControlControlType):
    def activate(self, conn: S2Connection) -> None:
        print("The control type NoControl is now activated.")

    def deactivate(self, conn: S2Connection) -> None:
        print("The control type NoControl is now deactivated.")


if __name__ == "__main__":
    # Configuration
    parser = argparse.ArgumentParser(description="S2 pairing example for FRBC RM")
    parser.add_argument("--pairing_endpoint", type=str, required=True)
    parser.add_argument("--pairing_token", type=str, required=True)

    args = parser.parse_args()

    pairing_endpoint = args.pairing_endpoint
    pairing_token = args.pairing_token

    # --- Client Setup ---
    # Create node description
    node_description = S2NodeDescription(
        brand="TNO",
        logoUri="https://www.tno.nl/publish/pages/5604/tno-logo-1484x835_003_.jpg",
        type="demo frbc example",
        modelName="S2 pairing example stub",
        userDefinedName="TNO S2 pairing example for frbc",
        role=S2Role.RM,
        deployment=Deployment.LAN,
    )

    # Create a client to perform the pairing
    client = S2DefaultClient(
        pairing_uri=pairing_endpoint,
        token=PairingToken(token=pairing_token),
        node_description=node_description,
        verify_certificate=False,
        supported_protocols=[Protocols.WebSocketSecure],
    )

    try:
        # # Request pairing
        # logger.info("Initiating pairing with endpoint: %s", pairing_endpoint)
        # pairing_response = client.request_pairing()
        # logger.info("Pairing request successful, requesting connection...")

        # # Request connection details
        # connection_details = client.request_connection()
        # logger.info("Connection request successful")

        # # Solve challenge
        # challenge_result = client.solve_challenge()
        # logger.info("Challenge solved successfully")

        s2_connection = S2Connection(
            url="wss://127.0.0.1:5000/v1",  # type: ignore
            role=EnergyManagementRole.RM,
            control_types=[MyFRBCControlType(), MyNoControlControlType()],
            asset_details=AssetDetails(
                resource_id=client.client_node_id,
                name="Some asset",
                instruction_processing_delay=Duration.from_milliseconds(20),
                roles=[Role(role=RoleType.ENERGY_CONSUMER, commodity=Commodity.ELECTRICITY)],
                currency=Currency.EUR,
                provides_forecast=False,
                provides_power_measurements=[CommodityQuantity.ELECTRIC_POWER_L1],
            ),
            reconnect=True,
            verify_certificate=False,
        )

        # Start S2 session with the connection details
        logger.info("Starting S2 session...")
        s2_connection.start_as_rm()
        logger.info("S2 session is running. Press Ctrl+C to exit.")

        # Keep the main thread alive to allow the WebSocket connection to run.
        event = threading.Event()
        event.wait()

    except KeyboardInterrupt:
        logger.info("Program interrupted by user.")
    except Exception as e:
        logger.error("Error during pairing process: %s", e, exc_info=True)
        raise e
    finally:
        client.close_connection()
        logger.info("Connection closed.")
