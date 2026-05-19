source_name_and_optional_id_transformation = [
    {
        "joinaggregate": [
            {"op": "distinct", "field": "source.id", "as": "distinct_ids_per_name"}
        ],
        "groupby": ["source.name"],
    },
    {
        "calculate": "datum.distinct_ids_per_name > 1 ? datum.source.name + ' (ID: ' + datum.source.id + ')' : datum.source.name",
        "as": "source_name_and_optional_id",
    },
]
