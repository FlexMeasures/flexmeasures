---
applyTo: "**/*.py"
---
# Python Docstrings

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
- Use line breaks only after punctuation (this facilitates review commenting and text searching).

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

## Comments

Comments explain *why*, not *what*. Avoid redundant comments that just restate the code. Include issue numbers or external links in TODO comments when relevant.
