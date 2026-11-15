"""Fetch the UI's third-party libraries, so FlexMeasures serves them itself rather than browsers loading them from CDNs.

Run it as ``python -m flexmeasures.ui.utils.fetch_vendor_assets``; see flexmeasures/ui/utils/vendor_assets.py.
It fetches the versions that the FLEXMEASURES_JS_VERSIONS setting sets, read from the config file that FlexMeasures reads.
It lives apart from vendor_assets.py, which flexmeasures.ui imports, so running it does not import itself twice.
"""

from __future__ import annotations

import argparse
import os
import sys

from flask import Config

from flexmeasures.ui.utils import vendor_assets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m flexmeasures.ui.utils.fetch_vendor_assets",
        description="Fetch the UI's third-party libraries, so FlexMeasures serves them itself rather than browsers loading them from CDNs.",
    )
    parser.add_argument(
        "keys",
        nargs="*",
        metavar="key",
        help=f"Libraries to fetch (default: all), from: {', '.join(vendor_assets.VENDOR_LIBRARIES)}.",
    )
    parser.add_argument(
        "--print-hashes",
        action="store_true",
        help="Print the hashes of the given libraries' files at their recorded versions, instead of fetching them.",
    )
    parser.add_argument(
        "--version",
        help="With --print-hashes and one library, print the hashes of this version instead, as an entry of the FLEXMEASURES_JS_VERSIONS setting.",
    )
    parser.add_argument(
        "--config",
        help="The config file to read FLEXMEASURES_JS_VERSIONS from (default: the one FlexMeasures reads, ~/.flexmeasures.cfg or the instance folder's flexmeasures.cfg).",
    )
    args = parser.parse_args(argv)
    unknown = [key for key in args.keys if key not in vendor_assets.VENDOR_LIBRARIES]
    if unknown:
        parser.error(f"unknown libraries: {', '.join(unknown)}")
    if args.version is not None and not (args.print_hashes and len(args.keys) == 1):
        parser.error("--version needs --print-hashes and one library")
    if args.config is not None and not os.path.isfile(args.config):
        parser.error(f"cannot find config file {args.config}")
    if args.print_hashes:
        for key in args.keys:
            print(f"{key}:")
            vendor_assets.print_hashes(key, version=args.version)
        return 0
    setting = read_js_versions_setting(args.config)
    libraries = vendor_assets.libraries_with_overrides(setting)
    written = vendor_assets.fetch(args.keys, libraries=libraries)
    print(f"Fetched {written} file(s) into {vendor_assets.VENDOR_DIR}.")
    for key in vendor_assets.unhashed_libraries(libraries):
        print(
            f"Skipped {key} {libraries[key].version}, as FLEXMEASURES_JS_VERSIONS sets it without hashes."
        )
    return 0


def read_js_versions_setting(path: str | None = None) -> dict | None:
    """The FLEXMEASURES_JS_VERSIONS setting from a config file, by default the one that FlexMeasures reads."""
    from flexmeasures.utils.config_utils import find_flexmeasures_cfg

    path = path or find_flexmeasures_cfg()
    if path is None or not os.path.isfile(path):
        return None
    config = Config(os.path.dirname(os.path.abspath(path)))
    config.from_pyfile(os.path.abspath(path))
    return config.get("FLEXMEASURES_JS_VERSIONS")


if __name__ == "__main__":
    sys.exit(main())
