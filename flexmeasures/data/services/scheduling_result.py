from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SchedulingJobResult:
    """Constraint analysis results from a scheduling job.

    Holds soft state-of-charge constraint analysis (unmet and satisfied targets) produced by the scheduler when optimizing storage devices.
    Results are available exclusively via ``GET /api/v3_0/jobs/<uuid>`` in the ``result`` field.

    The sensor schedule endpoint (``GET /api/v3_0/sensors/<id>/schedules/<job_id>``) returns power values only and does not include constraint analysis.

    **Structure:**
    Results contain four top-level fields:
    - ``unresolved``: List of soft constraints that the scheduler could not satisfy
      - Each entry is a dict with ``"asset"`` field (asset ID) and constraint-type keys (``"soc-minima"``, ``"soc-maxima"``)
      - Each constraint-type key holds a list of dicts, one per violated slot (chronologically ordered): ``{"datetime": ISO 8601 UTC, "violation": "X kWh"}``
    - ``resolved``: List of soft constraints that were satisfied with available headroom
      - Each entry is a dict with ``"asset"`` field and constraint-type keys
      - Each constraint-type key holds a list of dicts, one per met slot (chronologically ordered): ``{"datetime": ISO 8601 UTC, "margin": "X kWh"}``
    - ``outputs``: List of the sensors the schedule records on, one entry per sensor
      - Each entry is a dict with ``"sensor"`` field (sensor ID), ``"num-computed-beliefs"`` (the beliefs the scheduler computed for it),
        and ``"num-recorded-beliefs"`` (those recorded, which leaves out beliefs that repeat what is already on record).
      - On a dry run, nothing is recorded, so each entry's ``"num-recorded-beliefs"`` is 0.
    - ``num-beliefs``: Total number of beliefs (scheduled values) passed to the save, which is 0 on a dry run.

    **Important:** ``soc-targets`` (hard constraints) are never included since they are strictly enforced by the scheduler.
    Only hard constraint failures cause job failure.

    Example::

        {
            "unresolved": [
                {
                    "asset": 42,
                    "soc-minima": [
                        {"datetime": "2024-01-01T10:00:00+00:00", "violation": "260.0 kWh"},
                        {"datetime": "2024-01-01T10:15:00+00:00", "violation": "180.0 kWh"},
                    ],
                }
            ],
            "resolved": [
                {
                    "asset": 42,
                    "soc-maxima": [
                        {"datetime": "2024-01-01T12:00:00+00:00", "margin": "40.0 kWh"},
                    ],
                }
            ],
            "outputs": [
                {"sensor": 5, "num-computed-beliefs": 96, "num-recorded-beliefs": 96},
            ],
            "num-beliefs": 96
        }

    For usage examples and interpretation guidance, see :ref:`scheduling_constraint_results`.
    """

    unresolved: list = field(default_factory=list)
    resolved: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    num_beliefs: int = 0

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "unresolved": self.unresolved,
            "resolved": self.resolved,
            "outputs": self.outputs,
            "num-beliefs": self.num_beliefs,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SchedulingJobResult":
        """Deserialize from a dict."""
        return cls(
            unresolved=d.get("unresolved", []),
            resolved=d.get("resolved", []),
            outputs=d.get("outputs", []),
            num_beliefs=d.get("num-beliefs", 0),
        )
