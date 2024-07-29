""" FlexMeasures way of handling inflection """

from __future__ import annotations

import re
from typing import Any

import inflect
import inflection

p = inflect.engine()

# Give the inflection module some help for our domain
inflection.UNCOUNTABLES.add("solar")
inflection.UNCOUNTABLES.add("wind")
inflection.UNCOUNTABLES.add("evse")
ACRONYMS = ["EVSE"]


def capitalize(x: str, lower_case_remainder: bool = False) -> str:
    """Capitalize string with control over whether to lower case the remainder."""
    if lower_case_remainder:
        return x.capitalize()
    return x[0].upper() + x[1:]


def humanize(word):
    return inflection.humanize(word)


def parameterize(word):
    """Parameterize the word, so it can be used as a python or javascript variable name.
    For example:
    >>> word = "Acme® EV-Charger™"
    "acme_ev_chargertm"
    """
    return inflection.parameterize(word).replace("-", "_")


def pluralize(word, count: str | int | None = None):
    if word.lower().split()[-1] in inflection.UNCOUNTABLES:
        return word
    return p.plural(word, count)


def titleize(word):
    """Acronym exceptions are not yet supported by the inflection package,
    even though Ruby on Rails, of which the package is a port, does.

    In most cases it's probably better to use our capitalize function instead of titleize,
    because it has less unintended side effects. For example:
     >>> word = "two PV panels"
     >>> titleize(word)
     "Two Pv Panels"
     >>> capitalize(word)
     "Two PV panels"
    """
    word = inflection.titleize(word)
    for ac in ACRONYMS:
        word = re.sub(inflection.titleize(ac), ac, word)
    return word


def join_words_into_a_list(words: list[str]) -> str:
    return p.join(words, final_sep="")


def atoi(text):
    """Utility method for the `natural_keys` method."""
    return int(text) if text.isdigit() else text


def natural_keys(text: str):
    """Support for human sorting.

    `alist.sort(key=natural_keys)` sorts in human order.

    https://stackoverflow.com/a/5967539/13775459
    """
    return [atoi(c) for c in re.split(r"(\d+)", text)]


def human_sorted(alist: list, attr: Any | None = None, reverse: bool = False):
    """Human sort a list (for example, a list of strings or dictionaries).

    :param alist:   List to be sorted.
    :param attr:    Optionally, pass a dictionary key or attribute name to sort by
    :param reverse: If True, sorts descending.

    Example:
    >>> alist = ["PV 10", "CP1", "PV 2", "PV 1", "CP 2"]
    >>> sorted(alist)
    ['CP 2', 'CP1', 'PV 1', 'PV 10', 'PV 2']
    >>> human_sorted(alist)
    ['CP1', 'CP 2', 'PV 1', 'PV 2', 'PV 10']
    """
    if attr is None:
        # List of strings, to be sorted
        sorted_list = sorted(alist, key=lambda k: natural_keys(str(k)), reverse=reverse)
    else:
        try:
            # List of dictionaries, to be sorted by key
            sorted_list = sorted(
                alist, key=lambda k: natural_keys(k[attr]), reverse=reverse
            )
        except TypeError:
            # List of objects, to be sorted by attribute
            sorted_list = sorted(
                alist,
                key=lambda k: natural_keys(str(getattr(k, str(attr)))),
                reverse=reverse,
            )
    return sorted_list
