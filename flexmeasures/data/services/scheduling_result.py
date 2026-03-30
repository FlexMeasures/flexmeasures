from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SchedulingJobResult:
    """Results from a scheduling job, to be stored in the job's metadata.

    JSON serializable to enable storage in RQ job metadata and retrieval via the API.

    Note: ``soc-targets`` are modelled as hard constraints in the scheduler, meaning
    the scheduler will not allow any deviation from them by definition. Therefore,
    unmet ``soc-targets`` are not reported here.
    """

    unresolved_targets: dict = field(default_factory=dict)
    """First unmet ``soc-minima`` and/or ``soc-maxima`` targets, per sensor.

    The outer dict is keyed by sensor ID string (``str(sensor.id)``): the
    state-of-charge sensor if the device has one, otherwise the power sensor.
    Each value is a dict with constraint-type keys (``"soc-minima"`` and/or
    ``"soc-maxima"``), each mapping to:

    - ``"datetime"``: ISO 8601 UTC timestamp of the first violated constraint.
    - ``"delta"``: Always-positive magnitude of the violation in kWh,
      formatted as e.g. ``"260.0 kWh"``.
      For ``soc-minima`` this is the shortage (SoC fell short by this amount);
      for ``soc-maxima`` this is the excess (SoC exceeded the target by this amount).

    An empty dict means all targets have been met.

    Example::

        {
            "42": {
                "soc-minima": {"datetime": "2024-01-01T10:00:00+00:00", "delta": "260.0 kWh"},
            },
        }

    Devices with no violations are absent from the outer dict.
    """

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {"unresolved_targets": self.unresolved_targets}

    @classmethod
    def from_dict(cls, d: dict) -> "SchedulingJobResult":
        """Deserialize from a dict."""
        return cls(unresolved_targets=d.get("unresolved_targets", {}))
