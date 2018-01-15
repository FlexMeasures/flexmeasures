from collections import namedtuple


class Asset:
    """Each asset is a consuming or producing hardware."""

    def __init__(self, name: str, resource_type=None, area_code=""):
        self.orig_name = name
        self.resource_type = resource_type
        self.area_code = area_code

    @property
    def name(self) -> str:
        """The name we actually want to use"""
        repr_name = self.orig_name
        if self.resource_type == "solar":
            repr_name = repr_name.replace(" (MW)", "")
        return repr_name.replace(" ", "_").lower()

    @name.setter
    def name(self, new_name):
        self.name = new_name

    def to_dict(self):
        return dict(name=self.name, resource_type=self.resource_type, area_code=self.area_code)


# queries reference attributes from Asset to enable grouping and querying them
AssetQuery = namedtuple('AssetQuery', 'attr val')
