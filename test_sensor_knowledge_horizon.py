from flexmeasures.app import create_app
from flexmeasures.data.models.time_series import Sensor

# Create the Flask application instance
app = create_app()

# Run within the app context to access the database
with app.app_context():
    # Query the first available sensor
    sensor = Sensor.query.first()

    if sensor:
        print(f"--- Sensor {sensor.id}: {sensor.name} ---")

        # Access specifically the knowledge horizon attribute
        if hasattr(sensor, "knowledge_horizon"):
            print(f"Knowledge Horizon default: {sensor.knowledge_horizon}")
        else:
            print(
                "Sensor object does not have a 'knowledge_horizon' attribute directly."
            )

        print("\nAll properties in __dict__:")
        import pprint

        pprint.pprint(sensor.__dict__)

        # Knowledge horizon is sometimes stored in generic_asset or as a separate function.
        # Let's also check methods related to knowledge horizon if present:
        knowledge_methods = [m for m in dir(sensor) if "knowledge" in m.lower()]
        print(f"\nMethods/Attributes related to knowledge: {knowledge_methods}")
    else:
        print(
            "No sensors found in the database. Please ensure you have test data loaded."
        )
