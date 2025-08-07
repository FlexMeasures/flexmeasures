"""Temporary module which should move into coding_utils.py after get_downsample_function_and_value moves out of there."""

from functools import total_ordering


@total_ordering
class OrderByIdMixin:
    """
    Mixin class that adds rich comparison and hashing methods based on an ``id`` attribute.

    Classes inheriting from this mixin must define an ``id`` property or attribute
    that is an ``int`` or otherwise supports comparison and hashing.
    """

    def __eq__(self, other):
        """
        Return True if the ``id`` of both instances is equal.

        :param other: Another instance to compare.
        :return: True if ``self.id == other.id``, else False.
        """
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.id is None or other.id is None:
            raise ValueError(
                f"Cannot compare {self} and {other}: one or both have no ID."
            )
        return self.id == other.id

    def __lt__(self, other):
        """
        Return True if this instance's ``id`` is less than the other's.

        :param other: Another instance to compare.
        :return: True if ``self.id < other.id``, else False.
        """
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.id is None or other.id is None:
            raise ValueError(
                f"Cannot compare {self} and {other}: one or both have no ID."
            )
        return self.id < other.id

    def __hash__(self):
        """
        Return a hash based on the ``id`` attribute.

        This allows instances to be used in sets and as dictionary keys.

        :return: Hash value.
        """
        if self.id is None:
            raise TypeError(
                f"Unhashable object: {self} has no ID. Consider calling `db.session.flush()` before sensor objects in sets and as dictionary keys."
            )
        return hash(self.id)
