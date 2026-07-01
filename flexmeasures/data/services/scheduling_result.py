from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SchedulingJobResult:
    """Constraint analysis results from a scheduling job.

    Holds soft state-of-charge constraint analysis (unmet and satisfied targets) produced by the scheduler when optimizing storage devices.
    Results are keyed by asset ID and available exclusively via ``GET /api/v3_0/jobs/<uuid>`` in the ``scheduling_result`` field.

    The sensor schedule endpoint (``GET /api/v3_0/sensors/<id>/schedules/<job_id>``) returns power values only and does not include constraint analysis.

    **Structure:**
    Results contain two top-level fields:
    - ``unresolved``: Soft constraints that the scheduler could not satisfy
      - Dict keyed by asset ID with constraint-type keys (``"soc-minima"``, ``"soc-maxima"``)
      - Each entry: ``{"datetime": ISO 8601 UTC, "violation": "X kWh"}``
    - ``resolved``: Soft constraints that were satisfied with available headroom
      - Dict keyed by asset ID with constraint-type keys
      - Each entry: ``{"datetime": ISO 8601 UTC, "margin": "X kWh"}``

    **Important:** ``soc-targets`` (hard constraints) are never included since they are strictly enforced by the scheduler.
    Only hard constraint failures cause job failure.

    Example::

        {
            "unresolved": {
                "42": {
                    "soc-minima": {"datetime": "2024-01-01T10:00:00+00:00", "violation": "260.0 kWh"},
                },
            },
            "resolved": {
                "42": {
                    "soc-maxima": {"datetime": "2024-01-01T12:00:00+00:00", "margin": "40.0 kWh"},
                }
            }
        }

    For usage examples and interpretation guidance, see ``scheduling_constraint_results`` in the scheduling documentation.
    """

    unresolved: dict = field(default_factory=dict)
    resolved: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "unresolved": self.unresolved,
            "resolved": self.resolved,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SchedulingJobResult":
        """Deserialize from a dict."""
        return cls(
            unresolved=d.get("unresolved", {}),
            resolved=d.get("resolved", {}),
        )
