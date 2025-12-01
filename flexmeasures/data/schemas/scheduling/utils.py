import re


def rst_to_openapi(text: str) -> str:
    """
    Convert a string with RST markup to OpenAPI-safe text.

    - Replaces :abbr:`X (Y)` with <abbr title="Y">X</abbr>
    - Converts :math:`base^{exp}` into HTML sup/sub notation for OpenAPI
    - Removes any RST footnote references like [#]_ or [1]_ or [label]_
    """

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

    return text
