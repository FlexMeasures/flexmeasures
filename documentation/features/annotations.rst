.. _annotations:

Annotations
===========

Annotations allow you to attach contextual information to accounts, assets, or sensors over specific time periods. 
They help document important events, holidays, alerts, maintenance windows, or any other information that adds context to your time series data.


What are Annotations?
---------------------

An annotation is a piece of metadata associated with a specific entity (account, asset, or sensor) during a defined time period.
Each annotation includes:

- **Content**: Descriptive text (up to 1024 characters)
- **Time range**: Start and end times defining when the annotation applies
- **Type**: Category of the annotation (label, holiday, alert, warning, error, or feedback)
- **Belief time**: Timestamp when the annotation was created or became known
- **Source**: The data source that created the annotation (typically a user or automated system)


Use Cases
---------

Annotations are particularly useful for:

**Forecasting and Scheduling**
    Holiday annotations help forecasting algorithms understand when energy consumption patterns deviate from normal patterns.
    FlexMeasures can automatically import public holidays using the ``flexmeasures add holidays`` command.

**Data Quality Tracking**
    Mark periods with known sensor issues, data gaps, or quality problems using ``error`` or ``warning`` type annotations.
    This helps analysts understand why certain data points might be unreliable.

**Operational Documentation**
    Document maintenance windows, system changes, or configuration updates with ``label`` type annotations.
    Record feedback about system behavior for future reference.

**Alert Management**
    Create ``alert`` type annotations for active issues requiring attention.
    When resolved, the status changes and the annotation becomes part of the operational history.

**Asset Context**
    Mark special events at the asset level (e.g., building renovations, equipment upgrades).
    These annotations appear in all related sensor charts for that asset.


Annotation Types
----------------

FlexMeasures supports six annotation types:

``label``
    General-purpose annotations for documentation and notes. Default type if not specified.

``holiday``
    Public or organizational holidays that may affect energy patterns. Used by forecasting algorithms.

``alert``
    Active warnings requiring attention or action.

``warning``
    Informational warnings about potential issues or degraded conditions.

``error``
    Markers for periods with data quality issues, sensor failures, or system errors.

``feedback``
    User feedback or observations about system behavior or data.


Creating Annotations via API
-----------------------------

The annotation API provides three POST endpoints under development (``/api/dev/annotation/``):

- ``POST /api/dev/annotation/accounts/<id>`` - Annotate an account
- ``POST /api/dev/annotation/assets/<id>`` - Annotate an asset  
- ``POST /api/dev/annotation/sensors/<id>`` - Annotate a sensor

.. warning::
    These endpoints are experimental and part of the Developer API. They may change in future releases.
    See :ref:`dev` for the current API specification.


**Authentication**

All annotation endpoints require authentication. Include your access token in the request header:

.. code-block:: json

    {
        "Authorization": "Bearer <your-access-token>"
    }

See :ref:`api_auth` for details on obtaining an access token.


**Permissions**

You need ``update`` permission on the target entity (account, asset, or sensor) to create annotations.
The permission system ensures users can only annotate resources they have access to.

See :ref:`authorization` for more details on FlexMeasures authorization.


**Request Format**

All annotation endpoints accept the same request body format:

.. code-block:: json

    {
        "content": "Sensor maintenance performed",
        "start": "2024-12-15T09:00:00+01:00",
        "end": "2024-12-15T11:00:00+01:00",
        "type": "label",
        "belief_time": "2024-12-15T08:45:00+01:00"
    }

**Required fields:**

- ``content`` (string): Description of the annotation. Maximum 1024 characters.
- ``start`` (ISO 8601 datetime): When the annotated period begins. Must include timezone.
- ``end`` (ISO 8601 datetime): When the annotated period ends. Must be after ``start``. Must include timezone.

**Optional fields:**

- ``type`` (string): One of ``"alert"``, ``"holiday"``, ``"label"``, ``"feedback"``, ``"warning"``, ``"error"``. Defaults to ``"label"``.
- ``belief_time`` (ISO 8601 datetime): When the annotation was created or became known. Defaults to current time if omitted.

**Response Format**

Successful requests return the created annotation:

.. code-block:: json

    {
        "id": 123,
        "content": "Sensor maintenance performed",
        "start": "2024-12-15T09:00:00+01:00",
        "end": "2024-12-15T11:00:00+01:00",
        "type": "label",
        "belief_time": "2024-12-15T08:45:00+01:00",
        "source_id": 42
    }

The ``source_id`` identifies the data source that created the annotation (typically corresponds to the authenticated user).


**Status Codes**

- ``201 Created``: A new annotation was created
- ``200 OK``: An identical annotation already exists (idempotent behavior)
- ``400 Bad Request``: Invalid request data (e.g., end before start, missing required fields)
- ``401 Unauthorized``: Missing or invalid authentication token
- ``403 Forbidden``: User lacks permission to annotate this entity
- ``404 Not Found``: The specified account, asset, or sensor does not exist
- ``422 Unprocessable Entity``: Request data fails validation
- ``500 Internal Server Error``: Server error during annotation creation


Examples
--------

**Example 1: Mark a holiday on an asset**

.. code-block:: bash

    curl -X POST "https://company.flexmeasures.io/api/dev/annotation/assets/5" \
      -H "Authorization: Bearer YOUR_TOKEN_HERE" \
      -H "Content-Type: application/json" \
      -d '{
        "content": "Christmas Day - reduced operations",
        "start": "2024-12-25T00:00:00+01:00",
        "end": "2024-12-26T00:00:00+01:00",
        "type": "holiday"
      }'

**Response:**

.. code-block:: json

    {
        "id": 456,
        "content": "Christmas Day - reduced operations",
        "start": "2024-12-25T00:00:00+01:00",
        "end": "2024-12-26T00:00:00+01:00",
        "type": "holiday",
        "belief_time": "2024-12-15T10:30:00+01:00",
        "source_id": 12
    }

**Status:** ``201 Created``


**Example 2: Document a sensor error**

.. code-block:: bash

    curl -X POST "https://company.flexmeasures.io/api/dev/annotation/sensors/42" \
      -H "Authorization: Bearer YOUR_TOKEN_HERE" \
      -H "Content-Type: application/json" \
      -d '{
        "content": "Temperature sensor malfunction - readings unreliable",
        "start": "2024-12-10T14:30:00+01:00",
        "end": "2024-12-10T16:45:00+01:00",
        "type": "error"
      }'

**Response:**

.. code-block:: json

    {
        "id": 457,
        "content": "Temperature sensor malfunction - readings unreliable",
        "start": "2024-12-10T14:30:00+01:00",
        "end": "2024-12-10T16:45:00+01:00",
        "type": "error",
        "belief_time": "2024-12-15T10:35:00+01:00",
        "source_id": 12
    }

**Status:** ``201 Created``


**Example 3: Python client example**

.. code-block:: python

    import requests
    from datetime import datetime, timezone, timedelta

    # Configuration
    FLEXMEASURES_URL = "https://company.flexmeasures.io"
    ACCESS_TOKEN = "your-access-token-here"
    
    # Create annotation for an account
    annotation_data = {
        "content": "Office closed for renovation",
        "start": "2025-01-15T00:00:00+01:00",
        "end": "2025-01-22T00:00:00+01:00",
        "type": "label"
    }
    
    response = requests.post(
        f"{FLEXMEASURES_URL}/api/dev/annotation/accounts/3",
        headers={
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        },
        json=annotation_data
    )
    
    if response.status_code in (200, 201):
        annotation = response.json()
        print(f"Annotation created with ID: {annotation['id']}")
        if response.status_code == 200:
            print("(Annotation already existed)")
    else:
        print(f"Error: {response.status_code}")
        print(response.json())


**Example 4: Using Python helper function**

.. code-block:: python

    from datetime import datetime, timedelta, timezone
    import requests
    
    def create_annotation(entity_type, entity_id, content, start, end,
                         annotation_type="label", belief_time=None,
                         base_url="https://company.flexmeasures.io",
                         token=None):
        """Create an annotation via the FlexMeasures API.
        
        :param entity_type:     One of "accounts", "assets", "sensors"
        :param entity_id:       ID of the entity to annotate
        :param content:         Annotation text (max 1024 chars)
        :param start:           Start datetime (ISO 8601 string or datetime object)
        :param end:             End datetime (ISO 8601 string or datetime object)
        :param annotation_type: Type of annotation (default: "label")
        :param belief_time:     Optional belief time (ISO 8601 string or datetime object)
        :param base_url:        FlexMeasures instance URL
        :param token:           API access token
        :return:                Response JSON and status code tuple
        """
        # Convert datetime objects to ISO 8601 strings if needed
        if isinstance(start, datetime):
            start = start.isoformat()
        if isinstance(end, datetime):
            end = end.isoformat()
        if isinstance(belief_time, datetime):
            belief_time = belief_time.isoformat()
        
        url = f"{base_url}/api/dev/annotation/{entity_type}/{entity_id}"
        
        payload = {
            "content": content,
            "start": start,
            "end": end,
            "type": annotation_type
        }
        
        if belief_time:
            payload["belief_time"] = belief_time
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, headers=headers, json=payload)
        return response.json(), response.status_code
    
    # Example usage
    now = datetime.now(timezone.utc)
    result, status = create_annotation(
        entity_type="sensors",
        entity_id=123,
        content="Scheduled maintenance",
        start=now + timedelta(hours=2),
        end=now + timedelta(hours=4),
        annotation_type="label",
        token="your-token-here"
    )
    
    print(f"Status: {status}")
    print(f"Annotation ID: {result.get('id')}")


Idempotency
-----------

The annotation API is idempotent. If you POST the same annotation data twice (same content, start time, belief time, source, and type), 
the API will:

1. On first request: Create the annotation and return ``201 Created``
2. On subsequent identical requests: Return the existing annotation with ``200 OK``

This idempotency is based on a database uniqueness constraint on ``(content, start, belief_time, source_id, type)``.

**Why is this useful?**

- Safe to retry failed requests without creating duplicates
- Simplifies client code (no need to check if annotation exists first)
- Automated systems can safely re-run annotation creation scripts

**Note:** Annotations with the same content but different ``end`` times are considered different annotations. 
The ``end`` field is not part of the uniqueness constraint.


Creating Annotations via CLI
-----------------------------

FlexMeasures provides CLI commands for creating annotations:

**General annotation command:**

.. code-block:: bash

    flexmeasures add annotation \
      --content "Maintenance window" \
      --start "2024-12-20T10:00:00+01:00" \
      --end "2024-12-20T12:00:00+01:00" \
      --type label \
      --account-id 1

You can target accounts, assets, or sensors:

.. code-block:: bash

    # Annotate a specific sensor
    flexmeasures add annotation --sensor-id 42 --content "..." --start "..." --end "..."
    
    # Annotate a specific asset
    flexmeasures add annotation --asset-id 5 --content "..." --start "..." --end "..."
    
    # Annotate an account
    flexmeasures add annotation --account-id 1 --content "..." --start "..." --end "..."


**Holiday import command:**

FlexMeasures can automatically import public holidays using the `workalendar <https://github.com/workalendar/workalendar>`_ library:

.. code-block:: bash

    # Add holidays for a specific account
    flexmeasures add holidays --account-id 1 --year 2025 --country NL
    
    # Add holidays for an asset
    flexmeasures add holidays --asset-id 5 --year 2025 --country DE

See ``flexmeasures add holidays --help`` for available countries and options.


Viewing Annotations
-------------------

**In the FlexMeasures UI:**

Annotations appear automatically in:

- **Sensor charts**: Individual sensor data views show all annotations linked to that sensor, its asset, and its account
- **Asset views**: Display annotations associated with the asset and its parent account
- **Dashboard views**: Where relevant, annotations provide context to visualized data

Annotations are displayed as vertical bands or markers on time series charts, color-coded by type.

**Via API queries:**

When fetching sensor data through chart endpoints, you can control which annotations are included:

.. code-block:: bash

    GET /api/dev/sensor/42/chart?include_sensor_annotations=true&include_asset_annotations=true&include_account_annotations=true

This allows you to:

- Include only sensor-specific annotations
- Add broader context from asset and account annotations  
- Customize which annotation layers are visible

See :ref:`dev` for complete API documentation.


Best Practices
--------------

**Content Guidelines**

- Be concise but descriptive (you have 1024 characters)
- Include relevant context: who, what, why
- For errors, describe the impact and resolution status
- Use consistent formatting for similar annotation types

**Time Range Selection**

- Use precise start/end times for known events
- For ongoing issues, set end time to expected resolution or current time
- Consider timezone implications for multi-region deployments

**Type Selection**

- Use ``holiday`` for events that forecasting algorithms should consider
- Use ``error`` for data quality issues that affect analysis
- Use ``label`` for general documentation
- Use ``alert`` for active issues requiring attention
- Reserve ``warning`` for degraded but functioning conditions

**Organizational Practices**

- Establish annotation conventions within your team
- Document your annotation strategy in internal wikis
- Regularly review and update annotations as situations evolve
- Use CLI for bulk imports (e.g., yearly holidays)
- Use API for automated annotation creation from monitoring systems


Limitations and Roadmap
------------------------

**Current Limitations:**

- No bulk creation endpoint (must create annotations individually)
- No UPDATE or DELETE endpoints yet (annotations are immutable once created)
- No direct annotation query endpoint (must query via entity endpoints)
- Limited search/filter capabilities

**Planned Improvements:**

See the `FlexMeasures GitHub issues <https://github.com/FlexMeasures/flexmeasures/issues/470>`_ for ongoing annotation feature development.

Potential future enhancements:

- Bulk annotation creation and management
- Annotation editing and deletion via API
- Rich query interface for annotations
- Annotation templates for common scenarios
- Enhanced UI for annotation management
- Annotation export and reporting


See Also
--------

- :ref:`dev` - Complete Developer API documentation including current annotation endpoints
- :ref:`datamodel` - Overview of the FlexMeasures data model including annotations
- :ref:`cli` - Command-line interface documentation
- :ref:`auth` - Authentication and authorization details
