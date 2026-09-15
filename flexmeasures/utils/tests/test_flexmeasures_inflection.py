import pytest

from flexmeasures.utils.flexmeasures_inflection import (
    pluralize,
    join_words_into_a_list,
    indefinite_article,
)


@pytest.mark.parametrize(
    "word, count, include_count, expected",
    [
        ("asset", None, False, "assets"),
        ("asset", 1, False, "asset"),
        ("asset", "1", False, "asset"),
        ("asset", 2, False, "assets"),
        ("asset", 2, True, "2 assets"),
        ("account", None, False, "accounts"),
        ("battery", None, False, "batteries"),
        ("solar", None, False, "solar"),  # uncountable, added by flexmeasures
        ("wind", None, False, "wind"),  # uncountable, added by flexmeasures
        ("one-way_evse", None, False, "one-way_evses"),
    ],
)
def test_pluralize(word, count, include_count, expected):
    assert pluralize(word, count, include_count) == expected


@pytest.mark.parametrize(
    "words, conj, final_sep, expected",
    [
        ([], "and", "", ""),
        (["a"], "and", "", "a"),
        (["a", "b"], "and", "", "a and b"),
        (["a", "b", "c"], "and", "", "a, b and c"),
        (["a", "b", "c"], "and", ",", "a, b, and c"),
        (["a", "b", "c"], "or", ",", "a, b, or c"),
    ],
)
def test_join_words_into_a_list(words, conj, final_sep, expected):
    assert join_words_into_a_list(words, conj=conj, final_sep=final_sep) == expected


@pytest.mark.parametrize(
    "word, expected",
    [
        # Words used at our own call sites.
        ("power", "a"),
        ("energy price", "an"),
        ("capacity price", "a"),
        # Words a plain vowel-letter heuristic would get wrong.
        ("unit", "a"),
        ("hour", "an"),
        ("one-way_evse", "a"),
        ("euro", "a"),
        ("honest", "an"),
        # Capitalised abbreviations, which are read out letter by letter.
        ("MW", "an"),
        ("MWh", "an"),
        ("kW", "a"),
        ("EVSE", "an"),
        # Case matters here: "a UN resolution", but "an unusual day".
        ("UN", "a"),
        ("unusual", "an"),
    ],
)
def test_indefinite_article(word, expected):
    assert indefinite_article(word) == expected
