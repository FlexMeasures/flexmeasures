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

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {"unresolved_targets": self.unresolved_targets}

    @classmethod
    def from_dict(cls, d: dict) -> "SchedulingJobResult":
        """Deserialize from a dict."""
        return cls(unresolved_targets=d.get("unresolved_targets", {}))
