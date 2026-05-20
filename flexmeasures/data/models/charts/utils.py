"""Shared Vega-Lite transforms for chart source labels.

The source legend label transform keeps ``source.name`` visible and appends the
shortest available metadata that distinguishes sources with duplicate names. It
falls back to ``source.id`` only when non-ID source metadata is identical.
"""

source_legend_label_transformation = [
    {
        "calculate": "datum.source.display_type || datum.source.raw_type || datum.source.type || ''",
        "as": "source_display_type",
    },
    {
        "calculate": "datum.source.model || ''",
        "as": "source_model_detail",
    },
    {
        "calculate": "datum.source.version ? 'v' + datum.source.version : ''",
        "as": "source_version_detail",
    },
    {
        "joinaggregate": [
            {
                "op": "distinct",
                "field": "source.id",
                "as": "distinct_ids_per_source_name",
            }
        ],
        "groupby": ["source.name"],
    },
    {
        "calculate": "datum.source_display_type",
        "as": "source_type_detail",
    },
    {
        "joinaggregate": [
            {
                "op": "distinct",
                "field": "source.id",
                "as": "distinct_ids_per_source_name_and_type",
            }
        ],
        "groupby": ["source.name", "source_type_detail"],
    },
    {
        "joinaggregate": [
            {
                "op": "distinct",
                "field": "source.id",
                "as": "distinct_ids_per_source_name_and_model",
            }
        ],
        "groupby": ["source.name", "source_model_detail"],
    },
    {
        "joinaggregate": [
            {
                "op": "distinct",
                "field": "source.id",
                "as": "distinct_ids_per_source_name_and_version",
            }
        ],
        "groupby": ["source.name", "source_version_detail"],
    },
    {
        "calculate": "datum.source_type_detail && datum.source_model_detail ? datum.source_type_detail + ' ' + datum.source_model_detail : datum.source_type_detail || datum.source_model_detail",
        "as": "source_type_model_detail",
    },
    {
        "joinaggregate": [
            {
                "op": "distinct",
                "field": "source.id",
                "as": "distinct_ids_per_source_name_type_model",
            }
        ],
        "groupby": ["source.name", "source_type_model_detail"],
    },
    {
        "calculate": "datum.source_type_detail && datum.source_version_detail ? datum.source_type_detail + ' ' + datum.source_version_detail : datum.source_type_detail || datum.source_version_detail",
        "as": "source_type_version_detail",
    },
    {
        "joinaggregate": [
            {
                "op": "distinct",
                "field": "source.id",
                "as": "distinct_ids_per_source_name_type_version",
            }
        ],
        "groupby": ["source.name", "source_type_version_detail"],
    },
    {
        "calculate": "datum.source_model_detail && datum.source_version_detail ? datum.source_model_detail + ' ' + datum.source_version_detail : datum.source_model_detail || datum.source_version_detail",
        "as": "source_model_version_detail",
    },
    {
        "joinaggregate": [
            {
                "op": "distinct",
                "field": "source.id",
                "as": "distinct_ids_per_source_name_model_version",
            }
        ],
        "groupby": ["source.name", "source_model_version_detail"],
    },
    {
        "calculate": "datum.source_version_detail ? (datum.source_type_model_detail ? datum.source_type_model_detail + ' ' + datum.source_version_detail : datum.source_version_detail) : datum.source_type_model_detail",
        "as": "source_type_model_version_detail",
    },
    {
        "joinaggregate": [
            {
                "op": "distinct",
                "field": "source.id",
                "as": "distinct_ids_per_source_name_type_model_version",
            }
        ],
        "groupby": ["source.name", "source_type_model_version_detail"],
    },
    {
        "calculate": "datum.distinct_ids_per_source_name == 1 ? datum.source.name : datum.distinct_ids_per_source_name_and_type == 1 && datum.source_type_detail ? datum.source.name + ' (' + datum.source_type_detail + ')' : datum.distinct_ids_per_source_name_and_model == 1 && datum.source_model_detail ? datum.source.name + ' (' + datum.source_model_detail + ')' : datum.distinct_ids_per_source_name_and_version == 1 && datum.source_version_detail ? datum.source.name + ' (' + datum.source_version_detail + ')' : datum.distinct_ids_per_source_name_type_model == 1 && datum.source_type_model_detail ? datum.source.name + ' (' + datum.source_type_model_detail + ')' : datum.distinct_ids_per_source_name_type_version == 1 && datum.source_type_version_detail ? datum.source.name + ' (' + datum.source_type_version_detail + ')' : datum.distinct_ids_per_source_name_model_version == 1 && datum.source_model_version_detail ? datum.source.name + ' (' + datum.source_model_version_detail + ')' : datum.distinct_ids_per_source_name_type_model_version == 1 && datum.source_type_model_version_detail ? datum.source.name + ' (' + datum.source_type_model_version_detail + ')' : datum.source.name + ' (ID: ' + datum.source.id + ')'",
        "as": "source_legend_label",
    },
]
