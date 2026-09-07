import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "documentation"
    / "tut"
    / "scripts"
    / "run-data-ingestion.py"
)


def load_tutorial_module() -> ModuleType:
    """Load the executable tutorial without requiring the client dependency."""

    client_module = ModuleType("flexmeasures_client")
    client_module.FlexMeasuresClient = object
    spec = importlib.util.spec_from_file_location("run_data_ingestion", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous_client_module = sys.modules.get("flexmeasures_client")
    sys.modules["flexmeasures_client"] = client_module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_client_module is None:
            del sys.modules["flexmeasures_client"]
        else:
            sys.modules["flexmeasures_client"] = previous_client_module
    return module


def test_current_ingestion_method_is_preserved() -> None:
    tutorial = load_tutorial_module()

    class CurrentClient:
        async def post_sensor_data(self, **kwargs):
            return kwargs

    client = CurrentClient()
    original_method = client.post_sensor_data

    assert tutorial.enable_legacy_ingestion_method(client) is True
    assert client.post_sensor_data == original_method


def test_legacy_ingestion_method_gets_current_alias() -> None:
    tutorial = load_tutorial_module()

    class LegacyClient:
        def __init__(self):
            self.received_kwargs = None

        async def post_measurements(self, **kwargs):
            self.received_kwargs = kwargs

    client = LegacyClient()

    assert tutorial.enable_legacy_ingestion_method(client) is False
    asyncio.run(client.post_sensor_data(sensor_id=17, values=[1.0]))
    assert client.received_kwargs == {"sensor_id": 17, "values": [1.0]}
