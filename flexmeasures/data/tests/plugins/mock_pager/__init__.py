"""A plugin that serves no pages: it only registers a critical-automation-failure hook."""

__version__ = "0.1"

pages = []


def page_the_engineer_on_duty(failure):
    """Collect what the hook is told, as a host's pager would receive it."""
    pages.append(failure)


__automation_failure_hooks__ = [page_the_engineer_on_duty]
