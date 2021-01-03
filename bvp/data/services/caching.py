from time import time
import pickle

from flask_caching.backends.simple import SimpleCache
from timely_beliefs import BeliefsDataFrame

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource


class BVPSimpleCache(SimpleCache):
    """
    Patch in-built simple cache for oour purposes.
    """

    def get(self, key):
        try:
            print(f"[X] CACHE CHECK: {key}")
            expires, value = self._cache[key]
            if expires == 0 or expires > time():
                loaded = pickle.loads(value)
                if isinstance(loaded, BeliefsDataFrame):
                    for source in set(loaded.sources):
                        if isinstance(source, DataSource):
                            db.session.merge(source, load=False)
                return loaded
        except (KeyError, pickle.PickleError):
            print(f"[ ] CACHE CHECK: {key}")
            return None


def simple(app, config, args, kwargs):
    return BVPSimpleCache(*args, **kwargs)
