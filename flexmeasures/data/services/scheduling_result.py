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
    """First unmet ``soc-minima`` and/or ``soc-maxima`` targets, if any.

    Each present key maps to a dict with:

    - ``"datetime"``: ISO 8601 timestamp of the first violated constraint.
    - ``"delta"``: Signed difference (scheduled SoC minus target value) in MWh.
      A negative ``delta`` for ``soc-minima`` means the SoC is below the minimum;
      a positive ``delta`` for ``soc-maxima`` means the SoC exceeds the maximum.

    Example::

        {
            "soc-minima": {"datetime": "2024-01-01T10:00:00+00:00", "delta": -0.5},
            "soc-maxima": {"datetime": "2024-01-01T14:00:00+00:00", "delta": 0.3},
        }

    If a constraint type has no violation the key is absent.
    """

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {"unresolved_targets": self.unresolved_targets}

    @classmethod
    def from_dict(cls, d: dict) -> "SchedulingJobResult":
        """Deserialize from a dict."""
        return cls(unresolved_targets=d.get("unresolved_targets", {}))
