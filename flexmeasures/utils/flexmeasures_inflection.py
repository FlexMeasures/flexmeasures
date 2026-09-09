"""FlexMeasures way of handling inflection"""

from __future__ import annotations

import re
from typing import Any, Sequence

import inflection

# Give the inflection module some help for our domain
inflection.UNCOUNTABLES.update(["solar", "wind", "evse"])
ACRONYMS = ["EVSE"]


def capitalize(x: str, lower_case_remainder: bool = False) -> str:
    """Capitalize string with control over whether to lower case the remainder."""
    if lower_case_remainder:
        return x.capitalize()
    return x[0].upper() + x[1:]


def humanize(word):
    return inflection.humanize(word)


def parameterize(word):
    """Parameterize the word, so it can be used as a Python or JavaScript variable name.
    For example:
    >>> parameterize("Acme® EV-Charger™")
    'acme_ev_chargertm'
    """
    return inflection.parameterize(word).replace("-", "_")


def pluralize(word, count: str | int | None = None, include_count: bool = False):
    if word.lower().split()[-1] not in inflection.UNCOUNTABLES and count not in (
        1,
        "1",
    ):
        word = inflection.pluralize(word)
    return f"{count} {word}" if include_count else word


def indefinite_article(word: str) -> str:
    """Return "a" or "an", whichever fits in front of word, e.g. "power" -> "a", "energy price" -> "an".

    This is a simple vowel-letter heuristic (not a full pronunciation lookup), good enough
    for FlexMeasures' domain vocabulary (units, field names).
    """
    return "an" if word[:1].lower() in "aeiou" else "a"


def titleize(word):
    """Acronym exceptions are not yet supported by the inflection package,
    even though Ruby on Rails, of which the package is a port, does.

    In most cases it's probably better to use our capitalize function instead of titleize,
    because it has less unintended side effects. For example:
     >>> word = "two PV panels"
     >>> titleize(word)
     'Two Pv Panels'
     >>> capitalize(word)
     'Two PV panels'
    """
    word = inflection.titleize(word)
    for ac in ACRONYMS:
        word = re.sub(inflection.titleize(ac), ac, word)
    return word


def join_words_into_a_list(
    words: Sequence[str], conj: str = "and", final_sep: str = ""
) -> str:
    """Join words into a human-readable list, e.g. ["a", "b", "c"] -> "a, b and c".

    Pass final_sep="," for an Oxford comma before the conjunction (e.g. "a, b, and c"),
    and conj="or" for a disjunction (e.g. "a, b or c").
    """
    words = list(words)
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    if len(words) == 2:
        return f"{words[0]} {conj} {words[1]}"
    return f"{', '.join(words[:-1])}{final_sep} {conj} {words[-1]}"


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
