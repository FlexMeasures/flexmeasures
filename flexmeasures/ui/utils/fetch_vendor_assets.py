"""Fetch the UI's third-party libraries, so FlexMeasures serves them itself rather than browsers loading them from CDNs.

Run it as ``python -m flexmeasures.ui.utils.fetch_vendor_assets``; see flexmeasures/ui/utils/vendor_assets.py.
It lives apart from vendor_assets.py, which flexmeasures.ui imports, so running it does not import itself twice.
"""

from __future__ import annotations

import argparse
import sys

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
    args = parser.parse_args(argv)
    unknown = [key for key in args.keys if key not in vendor_assets.VENDOR_LIBRARIES]
    if unknown:
        parser.error(f"unknown libraries: {', '.join(unknown)}")
    if args.print_hashes:
        for key in args.keys:
            print(f"{key}:")
            vendor_assets.print_hashes(key)
        return 0
    written = vendor_assets.fetch(args.keys)
    print(f"Fetched {written} file(s) into {vendor_assets.VENDOR_DIR}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
