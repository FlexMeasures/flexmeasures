"""FlexMeasures way of handling inflection"""

from __future__ import annotations

import re
from functools import cache
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


# First match wins, "a" is the fallback.
# Ported from inflect's _indef_article_cases: https://github.com/jaraco/inflect/blob/main/inflect/__init__.py
# Two patterns are deliberately case-sensitive, to detect capitalised abbreviations such as "MW".
# Kept as source strings and compiled on first use.
_INDEF_ARTICLE_CASES: tuple[tuple[str, int, str], ...] = (
    # Ordinals such as "a 9th", "an 8th".
    (r"^([bcdgjkpqtuvwyz]-?th)", re.IGNORECASE, "a"),
    (r"^([aefhilmnorsx]-?th)", re.IGNORECASE, "an"),
    # Words starting with a silent or vowel-like consonant, e.g. "an hour", "an honest".
    (r"^((?:euler|hour(?!i)|heir|honest|hono[ur]|mpeg))", re.IGNORECASE, "an"),
    # Single letters, read out by name, e.g. "an F", "a B".
    (r"^[aefhilmnorsx]$", re.IGNORECASE, "an"),
    (r"^[bcdgjkpqtuvwyz]$", re.IGNORECASE, "a"),
    # Capitalised abbreviations read out letter by letter, e.g. "an MW", "an FTE".
    # Deliberately case-sensitive: only all-caps input is treated as an abbreviation.
    (
        r"""
^(?! FJO | [HLMNS]Y.  | RY[EO] | SQU
  | ( F[LR]? | [HL] | MN? | N | RH? | S[CHKLMNPTVW]? | X(YL)?) [AEIOU])
[FHLMNRSX][A-Z]
""",
        re.VERBOSE,
        "an",
    ),
    # Abbreviations written with a dot or hyphen, e.g. "an F.B.I.", "a B.A.".
    (r"^[aefhilmnorsx][.-]", re.IGNORECASE, "an"),
    (r"^[a-z][.-]", re.IGNORECASE, "a"),
    # Consonant-initial words (y counts as a consonant here), e.g. "a power".
    (r"^[^aeiouy]", re.IGNORECASE, "a"),
    # Vowel-initial words that are nonetheless pronounced with a consonant, e.g. "a euro", "a one-way".
    (r"^e[uw]", re.IGNORECASE, "a"),
    (r"^onc?e\b", re.IGNORECASE, "a"),
    (r"^onetime\b", re.IGNORECASE, "a"),
    (r"^uni([^nmd]|mo)", re.IGNORECASE, "a"),
    (r"^u[bcfghjkqrst][aeiou]", re.IGNORECASE, "a"),
    (r"^ukr", re.IGNORECASE, "a"),
    (r"^((?:unabomber|unanimous|US))", re.IGNORECASE, "a"),
    # Deliberately case-sensitive: "a UN resolution", but "an unusual day".
    (r"^U[NK][AIEO]?", 0, "a"),
    # Remaining vowel-initial words, e.g. "an energy price".
    (r"^[aeiou]", re.IGNORECASE, "an"),
    # Words starting with y that are pronounced with a vowel, e.g. "an ytterbium".
    (r"^(y(b[lor]|cl[ea]|fere|gg|p[ios]|rou|tt))", re.IGNORECASE, "an"),
)


@cache
def _compiled_indef_article_cases() -> tuple[tuple[re.Pattern, str], ...]:
    """Compile the indefinite article patterns, once, on first use."""
    return tuple(
        (re.compile(pattern, flags), article)
        for pattern, flags, article in _INDEF_ARTICLE_CASES
    )


def indefinite_article(word: str) -> str:
    """Return "a" or "an", whichever fits in front of word, e.g. "power" -> "a", "energy price" -> "an".

    The choice follows pronunciation rather than spelling, so a word starting with a vowel can still take "a" ("a unit"),
    a word starting with a consonant can take "an" ("an hour"),
    and an abbreviation takes whichever fits the letter it is read out as ("an MW").

    >>> indefinite_article("power")
    'a'
    >>> indefinite_article("energy price")
    'an'
    >>> indefinite_article("unit")
    'a'
    >>> indefinite_article("hour")
    'an'
    >>> indefinite_article("MW")
    'an'
    """
    for pattern, article in _compiled_indef_article_cases():
        if pattern.match(word):
            return article
    return "a"


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
