import re

import inflection


# Give the inflection module some help for our domain
inflection.UNCOUNTABLES.add("solar")
inflection.UNCOUNTABLES.add("wind")
inflection.UNCOUNTABLES.add("evse")
ACRONYMS = ["EVSE"]


def capitalize(x: str, lower_case_remainder: bool = False) -> str:
    """ Capitalize string with control over whether to lower case the remainder."""
    if lower_case_remainder:
        return x.capitalize()
    return x[0].upper() + x[1:]


def humanize(word):
    return inflection.humanize(word)


def parameterize(word):
    """Parameterize the word so it can be used as a python or javascript variable name.
    For example:
    >>> word = "Acme® EV-Charger™"
    "acme_ev_chargertm"
    """
    return inflection.parameterize(word).replace("-", "_")


def pluralize(word):
    if word.lower().split()[-1] in inflection.UNCOUNTABLES:
        return word
    return inflection.pluralize(word)


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
