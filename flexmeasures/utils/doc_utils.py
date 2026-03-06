import os
import re
from urllib.parse import quote_plus

DOCS_PATH = "/ui/static/documentation/html"


def rst_to_openapi(text: str) -> str:
    """
    Convert a string with RST markup to OpenAPI-safe text.

    - Replaces :ref:`to some section` with "the docs"
    - Replaces :ref:`section A <anchor>` with "section A in the docs"
    - Removes any RST footnote references like [#]_ or [1]_ or [label]_
    - Replaces :abbr:`X (Y)` with <abbr title="Y">X</abbr>
    - Converts :math:`base^{exp}` into HTML sup/sub notation for OpenAPI
    - Converts ``inline code`` to <code>
    - Converts **bold** to <strong>
    - Converts *italic* to <em>
    """

    # Replace cross-references with a mention of the docs
    def ref_repl(match):
        content = match.group(1)

        m = re.match(r"(.*?)\s*<([^>]+)>", content)
        if m:
            title = m.group(1).strip()
            search_term = title
        else:
            title = content.strip()
            search_term = title

        if sphinx_docs_exist():
            docs_path = DOCS_PATH
        else:
            docs_path = "https://flexmeasures.readthedocs.io/stable"
        url = docs_path + "/search.html?q=" + quote_plus(search_term)
        return f'<a href="{url}" target="_blank">the docs</a>'

    text = re.sub(r":ref:`([^`]+)`", ref_repl, text)

    # Remove footnote references
    text = re.sub(r"\s*\[[^\]]+?\]_", "", text)

    # Handle abbreviations
    def abbr_repl(match):
        content = match.group(1)
        if "(" in content and content.endswith(")"):
            abbr, title = content.split("(", 1)
            title = title[:-1]
            return f'<abbr title="{title.strip()}">{abbr.strip()}</abbr>'
        else:
            return content

    text = re.sub(r":abbr:`([^`]+)`", abbr_repl, text)

    # Handle math superscript
    def math_repl(match):
        expr = match.group(1)

        # Replace ALL occurrences of base^{exp}
        def sup_repl(power_match):
            base = power_match.group(1)
            exp = power_match.group(2)
            return f"{base}<sup>{exp}</sup>"

        # Pattern: base^{exp}, where base may include parentheses
        power_pattern = r"([A-Za-z0-9().+\-*/\s]+?)\s*\^\s*\{([^}]+)\}"

        converted = re.sub(power_pattern, sup_repl, expr)

        return converted

    text = re.sub(r":math:`([^`]+)`", math_repl, text)

    # Handle code snippets
    text = re.sub(r"``(.*?)``", r"<code>\1</code>", text)

    # Handle boldface
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)

    # Handle italics
    text = re.sub(r"\*(.*?)\*", r"<em>\1</em>", text)

    return text


def sphinx_docs_exist() -> bool:
    if os.path.exists(DOCS_PATH + "/index.html"):
        return True
    return False
