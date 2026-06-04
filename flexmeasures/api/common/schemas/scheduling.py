from flexmeasures.api.common.schemas.utils import make_openapi_compatible
from flexmeasures.data.schemas.scheduling.storage import StorageFlexModelSchema
from flexmeasures.data.schemas.scheduling import FlexContextSchema
from flexmeasures.data.schemas.sensors import SensorIdField


# Create FlexContext, FlexModel and AssetTrigger OpenAPI compatible schemas

storage_flex_model_schema_openAPI = make_openapi_compatible(
    StorageFlexModelSchema,
    include=[
        {
            "sensor": SensorIdField(
                metadata=dict(
                    description="ID of the device's power sensor.",
                )
            )
        }
    ],
)
flex_context_schema_openAPI = make_openapi_compatible(FlexContextSchema)
