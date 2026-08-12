from flexmeasures.utils.doc_utils import rst_to_openapi


def test_rst_to_openapi_preserves_cron_wildcards():
    assert rst_to_openapi("0 6 * * *") == "0 6 * * *"


def test_rst_to_openapi_converts_italic_emphasis():
    assert rst_to_openapi("Use *italic* text.") == "Use <em>italic</em> text."
