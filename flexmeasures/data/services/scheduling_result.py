from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SchedulingJobResult:
    """Results from a scheduling job, to be stored in the job's metadata.

    JSON serializable to enable storage in RQ job metadata and retrieval via the API.

    Holds constraint analysis results produced by the scheduler when optimizing a device with
    state-of-charge constraints. Results are available via ``GET /api/v3_0/jobs/<uuid>``,
    as part of the ``result`` object with ``unresolved`` and ``resolved`` arrays, keyed by asset ID.

    **Important Notes:**

    - ``soc-targets`` are modelled as hard constraints in the scheduler, meaning the scheduler will not
      allow any deviation from them by definition. Therefore, unresolved ``soc-targets`` are not reported here.
    - Empty dicts/arrays in results mean either all constraints were satisfied or no constraints were defined.

    See :ref:`scheduling_constraint_results` in the scheduling documentation for usage examples
    and interpretation guidance.

    The ``unresolved`` field holds per-sensor dicts keyed by ``"soc-minima"``/``"soc-maxima"``,
    each with ``"datetime"`` and ``"violation"`` keys. The ``resolved`` field holds the same structure
    but with ``"margin"`` instead of ``"violation"``.
    """

    unresolved: dict = field(default_factory=dict)
    """First violated ``soc-minima`` and/or ``soc-maxima`` constraint per sensor.

    Keyed by state-of-charge sensor ID string (``str(sensor.id)``). Each value is a dict with
    constraint-type keys (``"soc-minima"`` and/or ``"soc-maxima"``), each mapping to:

    - ``"datetime"``: ISO 8601 UTC timestamp of the first violated constraint.
    - ``"violation"``: Always-positive magnitude of the violation in kWh, e.g. ``"260.0 kWh"``.
      For ``soc-minima`` this is the shortage; for ``soc-maxima`` this is the excess.

    An empty dict means all targets have been met (or no state-of-charge sensor is set).
    Devices with no violations are absent from the outer dict.

    Example::

        {
            "42": {
                "soc-minima": {"datetime": "2024-01-01T10:00:00+00:00", "violation": "260.0 kWh"},
            },
        }
    """

    resolved: dict = field(default_factory=dict)
    """Tightest met ``soc-minima`` and/or ``soc-maxima`` constraint per sensor.

    Keyed by state-of-charge sensor ID string (``str(sensor.id)``). Each value is a dict with
    constraint-type keys (``"soc-minima"`` and/or ``"soc-maxima"``), each mapping to:

    - ``"datetime"``: ISO 8601 UTC timestamp of the tightest constraint slot (smallest positive margin).
    - ``"margin"``: Non-negative headroom in kWh, e.g. ``"40.0 kWh"``.
      For ``soc-minima`` this is how far above the minimum the SoC stayed;
      for ``soc-maxima`` this is how far below the maximum the SoC stayed.

    An empty dict means no constraints of that type were defined (or no state-of-charge sensor is set).
    Devices with no resolved constraints are absent from the outer dict.

    Example::

        {
            "42": {
                "soc-maxima": {"datetime": "2024-01-01T12:00:00+00:00", "margin": "40.0 kWh"},
            },
        }
    """

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
