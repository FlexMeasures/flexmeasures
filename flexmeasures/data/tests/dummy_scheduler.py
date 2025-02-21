from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.utils import initialize_series
from flexmeasures.utils.unit_utils import ur


class DummyScheduler(Scheduler):

    __author__ = "Test Organization"
    __version__ = "3"

    def compute(self):
        """
        Just a dummy scheduler that always plans to consume at maximum capacity.
        (Schedulers return positive values for consumption, and negative values for production)
        """
        capacity = self.sensor.get_attribute(
            "capacity_in_mw",
            ur.Quantity(self.sensor.get_attribute("site-power-capacity"))
            .to("MW")
            .magnitude,
        )
        return initialize_series(  # simply creates a Pandas Series repeating one value
            data=capacity,
            start=self.start,
            end=self.end,
            resolution=self.resolution,
        )

    def deserialize_config(self):
        """Do not care about any config sent in."""
        self.config_deserialized = True
