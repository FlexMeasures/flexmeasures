---
applyTo: "**/*.py,**/*.js,**/*.html"
---
# Docstrings and comments

The line-break rule under "Key conventions" applies to every language in this repo.
The rest of this file is Python-specific, except for the "JavaScript" section near the end.

## Python docstrings

All public functions, methods, and classes must have docstrings. Use RST (reStructuredText) format for Sphinx compatibility.

## Standard function docstring

```python
def function_name(param1: str, param2: int) -> bool:
    """One-line summary ending with a period.

    Longer description explaining purpose and usage when needed.
    Parameter descriptions are aligned and separated from the colon
    with at least one space.

    :param param1:      Description of param1.
    :param param2:      Description of param2.
    :returns:           Description of return value.
    :raises ValueError: When param1 is empty.

    Example::

        >>> function_name("test", 42)
        True
    """
```

## Key conventions

- One-line summary ends with a period and fits on one line.
- Leave one blank line between the summary and the extended description.
- Align `:param name:` descriptions using spaces (not tabs) for readability.
- Use `Example::` (double colon) to introduce a doctest block.
- Complement type hints — don't duplicate them in the docstring text.
- Use exactly one space after punctuation (no double spaces after periods).
- Use line breaks only after punctuation (this facilitates review commenting and text searching). This applies to in-line comments as well, not only docstrings; keep in-line comments short. So never wrap a docstring or comment in the middle of a phrase; each physical line must end at a comma, semicolon, colon, or period. (E501 is ignored and `max-line-length` is 160, so a long clause on one line is preferred over a mid-phrase break.) The same holds for JavaScript, see below.

## For code review (incl. automated reviewers)

The line-break-after-punctuation rule above is a deliberate, load-bearing convention (stable review comments and text search), not a stylistic nicety. When reviewing a change, always report a docstring or comment that wraps mid-phrase as a review comment; do not treat such a finding as low-confidence, and do not omit or suppress it. This applies to JavaScript comments too, not only Python docstrings.

## Click CLI commands

```python
@click.command()
def my_command():
    """One-line summary of what the command does.

    Longer description with usage context and examples if helpful.
    """
```

## Doctests

Include doctests in docstrings for pure utility functions. Run them with:

```bash
pytest --doctest-modules
```

Doctests in `documentation/` are also executed. Keep examples accurate and test them before committing.

## JavaScript

The line-break-after-punctuation rule applies to JSDoc blocks and to `//` comments, in `.js` files and in the `<script>` blocks of Jinja templates alike. There is no line-length linter for JavaScript here, so prefer a long clause on one line over a mid-phrase break, exactly as in Python.

```javascript
/**
 * One-line summary ending with a period.
 *
 * A longer description, broken only after punctuation,
 * so that each physical line ends at a comma, semicolon, colon, or period.
 *
 * @param {string} name - Description of the parameter.
 * @returns {number} - Description of the return value.
 */
```

`@param` and `@returns` lines are exempt: keep each on one line, however long.

## Comments

Comments explain *why*, not *what*. Avoid redundant comments that just restate the code. Include issue numbers or external links in TODO comments when relevant.
