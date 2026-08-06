"""
Contract between code that logs errors and the Sentry event filters serving them.
"""

SENTRY_DEDUPLICATION_KEY_ATTRIBUTE = "fm_sentry_deduplication_key"
"""Log record attribute asking Sentry to report the record once a UTC calendar day.

Set it through the `extra` argument of a logging call to say that repeated reports of the same condition are not worth their own Sentry event.
Records carrying the same key within a calendar day are reported once; records with a different key, or without the attribute, are reported as usual.
Keep the key stable for one condition, and let it cover the values that make one occurrence worth reporting separately from another.
"""
