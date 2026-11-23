from flexmeasures.auth.loaders import flex_context_loader


def test_flex_context_loader_reads_bare_ids_and_reference_objects(
    db, add_battery_assets
):
    """A field named after a sensor may hold a bare ID (such as ``consumption-price-sensor``),
    or a sensor reference object (such as ``reference-sensor``), and lists of either.
    """
    sensor = add_battery_assets["Test battery"].sensors[0]
    sensor_refs = flex_context_loader(
        {
            "consumption-price-sensor": sensor.id,
            "reference-sensor": {"sensor": sensor.id},
            "response-order": [{"sensor": sensor.id}],
            "inflexible-device-sensors": [sensor.id],
        }
    )
    labels = list(sensor_refs.keys())
    assert len(labels) == 4
    assert all(found == [sensor] for found in sensor_refs.values())
    assert any("'reference-sensor': 'sensor'" in label for label in labels)
    assert any("'response-order': {0: 'sensor'}" in label for label in labels)
