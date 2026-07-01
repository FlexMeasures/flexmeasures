from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SchedulingJobResult:
    """Results from a scheduling job, to be stored in the job's metadata.

    JSON serializable to enable storage in RQ job metadata and retrieval via the API.

    **Core Purpose:**
    Holds constraint analysis results produced by the scheduler when optimizing devices with
    state-of-charge constraints. Results are **keyed by asset ID** and available exclusively
    via ``GET /api/v3_0/jobs/<uuid>`` in the ``scheduling_result`` field.

    **Backward Compatibility Note:**
    Constraint analysis results were previously available via the sensor schedule endpoint
    but are now only available through the jobs endpoint. Clients must migrate to use the jobs
    endpoint for constraint analysis.

    **Structure:**
    Results contain two top-level fields:
    - ``unresolved``: Soft constraints that the scheduler could not satisfy
    - ``resolved``: Soft constraints that were satisfied with available headroom

    Each field is a dict keyed by asset ID, with constraint types as subkeys:
    - ``"soc-minima"``: State-of-charge minimum constraint
    - ``"soc-maxima"``: State-of-charge maximum constraint

    Each constraint entry contains:
    - ``"datetime"``: ISO 8601 UTC timestamp of first violation/tightest constraint
    - ``"violation"`` (unresolved only): Magnitude of violation in kWh
    - ``"margin"`` (resolved only): Headroom in kWh

    **Important Notes:**
    - ``soc-targets`` are modelled as hard constraints in the scheduler and are not reported here
    - Empty structures mean either all constraints were satisfied or no constraints were defined
    - For usage examples and interpretation guidance, see :ref:`scheduling_constraint_results`
      in the scheduling documentation
    """

    unresolved: dict = field(default_factory=dict)
    """First violated soft constraint per asset, keyed by asset ID.

    Each asset maps to a dict with constraint-type keys (``"soc-minima"`` and/or ``"soc-maxima"``),
    each containing:

    - ``"datetime"``: ISO 8601 UTC timestamp of the first constraint violation.
    - ``"violation"``: Always-positive magnitude of the violation in kWh.
      For ``soc-minima``: shortage below minimum. For ``soc-maxima``: excess above maximum.

    Empty when all constraints satisfied or none defined. Assets with no violations are absent.

    Example::

        {
            "42": {
                "soc-minima": {"datetime": "2024-01-01T10:00:00+00:00", "violation": "260.0 kWh"},
            },
        }
    """

    resolved: dict = field(default_factory=dict)
    """Tightest met soft constraint per asset, keyed by asset ID.

    Each asset maps to a dict with constraint-type keys (``"soc-minima"`` and/or ``"soc-maxima"``),
    each containing:

    - ``"datetime"``: ISO 8601 UTC timestamp of the tightest constraint (smallest positive margin).
    - ``"margin"``: Non-negative headroom in kWh.
      For ``soc-minima``: how far above minimum the SoC stayed.
      For ``soc-maxima``: how far below maximum the SoC stayed.

    Empty when no constraints of that type defined. Assets with no resolved constraints are absent.

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
