# Vendored UI assets

Third-party JS, CSS, fonts and images which the FlexMeasures UI serves itself, so it works without internet access.
Each library lives in `<lib>/<version>/`, where `<lib>` is its key in `flexmeasures/ui/utils/vendor_versions.py`.
Templates load them only through the macros in `flexmeasures/ui/templates/includes/vendor.html`.
The exception is `iconify/`: unversioned asset type icons from iconify.design, which `SVG_ICON_MAPPING` in `flexmeasures/ui/utils/view_utils.py` refers to by path.

## Bumping a library

1. Download the new version's files into `<lib>/<new version>/`, with the same file names and relative layout as the current version (stylesheets refer to their fonts and images by relative path).
2. Update the version in `flexmeasures/ui/utils/vendor_versions.py`.
3. Delete `<lib>/<old version>/`.
4. Run `pytest flexmeasures/ui/tests/test_vendor_assets.py`, and click through the pages that use the library.

Two paths are written out in `flexmeasures/ui/static/css/flexmeasures.css` rather than taken from `vendor_versions.py`, because a static stylesheet cannot read it:
`datatables/<version>/images/` (sort icons) and `poppins/v20/` (font).
Update those too when bumping DataTables.

## Sources

Files are unmodified copies of the npm packages on cdn.jsdelivr.net,
except DataTables (cdn.datatables.net), Poppins (fonts.gstatic.com) and the icons (api.iconify.design).
