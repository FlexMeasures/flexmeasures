"""Check the UI's third-party libraries for known security advisories, in the OSV database (https://osv.dev).

Reads the libraries and their versions from flexmeasures/ui/utils/vendor_assets.py,
and exits with 1 if any of them has an advisory that is not ignored below.
Run by .github/workflows/ui-library-advisories.yml.
It needs only Flask, which vendor_assets.py imports, so it does not install FlexMeasures.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Callable

VENDOR_ASSETS = (
    Path(__file__).resolve().parents[1]
    / "flexmeasures"
    / "ui"
    / "utils"
    / "vendor_assets.py"
)
OSV_API = "https://api.osv.dev/v1"

# Advisories which OSV reports for a version that the advisory itself shows is not affected,
# by (advisory, npm package, version), with the reason.
IGNORED: dict[tuple[str, str, str], str] = {
    (
        "GHSA-7f2v-3qq3-vvjf",
        "vega",
        "5.33.1",
    ): "The advisory names vega-expression 5.2.1 as the fix outside ESM, and vega 5.33.1 depends on vega-expression ~5.2.1.",
}


def load_libraries() -> dict:
    """VENDOR_LIBRARIES, read from vendor_assets.py without importing the flexmeasures package."""
    spec = importlib.util.spec_from_file_location("vendor_assets", VENDOR_ASSETS)
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look up their module while being defined.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.VENDOR_LIBRARIES


def query_osv(packages: list[tuple[str, str]]) -> list[list[str]]:
    """IDs of the advisories which affect each (npm package, version)."""
    query = {
        "queries": [
            {"package": {"name": name, "ecosystem": "npm"}, "version": version}
            for name, version in packages
        ]
    }
    request = urllib.request.Request(
        f"{OSV_API}/querybatch",
        data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        results = json.load(response)["results"]
    return [[vuln["id"] for vuln in result.get("vulns", [])] for result in results]


def summarize(advisory: str) -> str:
    with urllib.request.urlopen(f"{OSV_API}/vulns/{advisory}", timeout=60) as response:
        return json.load(response).get("summary", "")


def find_advisories(
    libraries: dict,
    query: Callable[[list[tuple[str, str]]], list[list[str]]] = query_osv,
) -> list[tuple[str, str, str, str]]:
    """(key, npm package, version, advisory) for each advisory affecting a library, except the ignored ones."""
    checked = [
        (key, library.npm_name, library.version)
        for key, library in libraries.items()
        if library.npm_name
    ]
    results = query([(name, version) for _, name, version in checked])
    return [
        (key, name, version, advisory)
        for (key, name, version), advisories in zip(checked, results)
        for advisory in advisories
        if (advisory, name, version) not in IGNORED
    ]


def main() -> int:
    found = find_advisories(load_libraries())
    if found:
        lines = [
            "## UI libraries with known advisories",
            "",
            "| Library | npm package | Version | Advisory | Summary |",
            "|---|---|---|---|---|",
        ]
        for key, name, version, advisory in found:
            lines.append(
                f"| {key} | {name} | {version} | https://osv.dev/vulnerability/{advisory} | {summarize(advisory)} |"
            )
        lines.append("")
        lines.append(
            "Bump each library in flexmeasures/ui/utils/vendor_assets.py to a version with a fix, "
            "or, if the advisory does not apply to that version, add it to IGNORED in ci/check_ui_library_advisories.py with the reason."
        )
    else:
        lines = ["No known advisories affect the UI's libraries."]
    report = "\n".join(lines)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(report + "\n")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
