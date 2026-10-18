"""Third-party libraries which the UI loads, and where it loads them from.

Each library is served by FlexMeasures from static/vendor/<key>/<version>/ when its files were fetched there,
and loaded from its CDN otherwise, with the hash recorded below as the tag's integrity attribute.
The Docker image comes with the files fetched.
To serve them from a pip-installed FlexMeasures, for example without internet access, fetch them once:

    python -m flexmeasures.ui.utils.fetch_vendor_assets

Fetching also stores each library's licence next to its files, and fails on any file whose hash does not match.
Templates load these libraries through the macros in templates/includes/vendor.html.

To bump a library, change its version below, then print the hashes of its files at that version, and paste them in:

    python -m flexmeasures.ui.utils.fetch_vendor_assets --print-hashes <key>

Every week, .github/workflows/ui-library-advisories.yml looks up these versions in the OSV database of security advisories.

This is a leaf module, so flexmeasures/ui/__init__.py can import it without an import cycle.
"""

from __future__ import annotations

import base64
import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from flask import url_for
from markupsafe import Markup, escape

VENDOR_DIR = Path(__file__).resolve().parents[1] / "static" / "vendor"
NPM_CDN = "https://cdn.jsdelivr.net/npm/{name}@{version}/"


@dataclass(frozen=True)
class VendorLibrary:
    """A library's version, its files with their SHA-256 hashes, and where to download them."""

    name: (
        str  # npm package name, or the library's own name if it does not come from npm
    )
    version: str
    files: dict[str, str]  # path relative to the base URL -> SHA-256 hash
    license: str  # path relative to the base URL, or a full URL
    license_sha256: str
    base_url: str = NPM_CDN  # formatted with the name and version
    # For a library not served from npm, the npm package to look up advisories for.
    npm_package: str | None = None

    @property
    def npm_name(self) -> str | None:
        """The npm package which this library is published as, if any, which advisory databases know it by."""
        if self.npm_package:
            return self.npm_package
        return self.name if self.base_url == NPM_CDN else None

    def url(self, path: str) -> str:
        return self.base_url.format(name=self.name, version=self.version) + path

    @property
    def license_url(self) -> str:
        return self.license if "://" in self.license else self.url(self.license)

    @property
    def license_path(self) -> str:
        """Where the licence is stored, relative to the library's local directory."""
        return (
            self.license.rsplit("/", 1)[-1] if "://" in self.license else self.license
        )


VENDOR_LIBRARIES: dict[str, VendorLibrary] = {
    "vega": VendorLibrary(
        name="vega",
        version="5.22.1",
        files={
            "build/vega.min.js": "731f01b68116bc185a196322096ca342737424c4995c48a6674f57ebc967e9c1",
        },
        license="LICENSE",
        license_sha256="b75f7ed0af20dedadf92c52bc236161bcf0d294ff2e6e34ca76403203349f71d",
    ),
    "vegaembed": VendorLibrary(
        name="vega-embed",
        version="6.21.0",
        files={
            "build/vega-embed.min.js": "fd72eab487018408e196630e6b3db75005f30604329b3eb40fbdfe3dfacadb8c",
        },
        license="LICENSE",
        license_sha256="32df67148f0fc3db0eb9e263a7b75d07f1eb14c61955005a4a39c6918d10d137",
    ),
    "vegalite": VendorLibrary(
        name="vega-lite",
        version="5.5.0",  # "5.6.0" has a problematic bar chart: see our sensor page and https://github.com/vega/vega-lite/issues/8496
        files={
            "build/vega-lite.min.js": "4804d726d5eb7f7d0335ce234481c6a51ceb3ef2f0031d544a80f381d1f4163d",
        },
        license="LICENSE",
        license_sha256="f618900fd0d64046963b29f40590cdd1e341a2f41449f99110d82fd81fea808c",
    ),
    "echarts": VendorLibrary(
        name="echarts",
        version="5.6.0",  # used for the fast (canvas-based) chart mode
        files={
            "dist/echarts.min.js": "bf4a223524e40b77c304bec67e1222cf551f14880cf42c69dc046558e11c07b1",
        },
        license="LICENSE",
        license_sha256="634293835b43a6dd2094fa39182a3d9a6b9ca43b7fdb9ac354e8037af2a3093a",
    ),
    "currencysymbolmap": VendorLibrary(
        name="currency-symbol-map",
        version="5.1.0",
        files={
            "map.js": "22c8c8381435b89abbc8786bb7d8c41ea06236113117c61bdb38c6c3a51b4e50",
        },
        license="LICENSE.md",
        license_sha256="db6bef538dd26785fb7b22de741b04a85121ccaa19568af310b97dcd3629a331",
    ),
    "jsoneditor": VendorLibrary(
        name="@json-editor/json-editor",
        version="2.15.2",
        files={
            "dist/jsoneditor.min.js": "e1339ef686f3e750ee520f534a24512df9f0891e5848b271ae03cb9d8629428f",
        },
        license="LICENSE",
        license_sha256="2c3d6f6bad4123d4f2abf92666e17adc3fc30a956e3b03c78b108c2a29630252",
    ),
    "leaflet": VendorLibrary(
        name="leaflet",
        version="1.9.4",
        files={
            "dist/leaflet.css": "a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6",
            "dist/leaflet-src.min.js": "3c3ccb000ef205c785428a4385281c8ca0aadfc00df0a686d3ddd4332131f2ce",
            "dist/images/layers-2x.png": "066daca850d8ffbef007af00b06eac0015728dee279c51f3cb6c716df7c42edf",
            "dist/images/layers.png": "1dbbe9d028e292f36fcba8f8b3a28d5e8932754fc2215b9ac69e4cdecf5107c6",
            "dist/images/marker-icon-2x.png": "00179c4c1ee830d3a108412ae0d294f55776cfeb085c60129a39aa6fc4ae2528",
            "dist/images/marker-icon.png": "574c3a5cca85f4114085b6841596d62f00d7c892c7b03f28cbfa301deb1dc437",
            "dist/images/marker-shadow.png": "264f5c640339f042dd729062cfc04c17f8ea0f29882b538e3848ed8f10edb4da",
        },
        license="LICENSE",
        license_sha256="53e8dc25862014e4324741ca18fbe3611e11d42ef69f59f86ea8c5389647d4cb",
    ),
    "leafletmarkercluster": VendorLibrary(
        name="leaflet.markercluster",
        version="1.5.3",
        files={
            "dist/MarkerCluster.css": "614dea0a98ff3f4ead74f04918f6b1d1b9ba435c25b5fc23b21a394d1e3e4d87",
            "dist/MarkerCluster.Default.css": "61258232d98d64dc2a7b1e02130d67421bc5b9bda5994eef70228ff97570c170",
            "dist/leaflet.markercluster.js": "1e4e1d22972a3926f48598e0caf14e3fe7049835d428a344fed4f9e3665b3508",
        },
        license="MIT-LICENCE.txt",
        license_sha256="3133dacd38250bd1f524d8166cc60a016a382522e062fce143691c65bf5e4b3d",
    ),
    "leafletmarkerclusterlayersupport": VendorLibrary(
        name="leaflet.markercluster.layersupport",
        version="2.0.1",
        files={
            "dist/leaflet.markercluster.layersupport.js": "7a61dfa8cb8829a81800a309ab8d4ebbe81fb309db22df670286dce66acd6bd8",
        },
        license="LICENSE",
        license_sha256="ca934ce716095f28879e54a71b5dddd742bdf7cb72ca0d7cc9d1a6892d66aca6",
    ),
    "jquery": VendorLibrary(
        name="jquery",
        version="3.5.1",
        files={
            "dist/jquery.min.js": "f7f6a5894f1d19ddad6fa392b2ece2c5e578cbf7da4ea805b6885eb6985b6e3d",
        },
        license="LICENSE.txt",
        license_sha256="1ff603118efdb313799567cb4a408594954384f40843ca6f29c596f5b1f8907d",
    ),
    "floatthead": VendorLibrary(
        name="floatthead",
        version="2.2.1",
        files={
            "dist/jquery.floatThead.min.js": "020bcbcff534803c840937a0eab0f671cd3ecb4240ed49656aaf76ae99bab730",
        },
        license="LICENSE",
        license_sha256="99c0cb82d16f11c4e3d92b856664ccc820f4d369a962c00ab16856926fe9accf",
    ),
    "bootstrap": VendorLibrary(
        name="bootstrap",
        version="5.3.3",
        files={
            "dist/css/bootstrap.min.css": "3c8f27e6009ccfd710a905e6dcf12d0ee3c6f2ac7da05b0572d3e0d12e736fc8",
            "dist/js/bootstrap.bundle.min.js": "0833b2e9c3a26c258476c46266e6877fc75218625162e0460be9a3a098a61c6c",
        },
        license="LICENSE",
        license_sha256="8c14611ae41ac6fd543c13349f22188eb12c69b3e59105c5eca3925a8e4eca3e",
    ),
    "bootstrapicons": VendorLibrary(
        name="bootstrap-icons",
        version="1.10.5",
        files={
            "font/bootstrap-icons.css": "d8824f7067cdfea38afec7e9ffaf072125266824206d69ef1f112d72153a505e",
            "font/fonts/bootstrap-icons.woff": "999550fafbfbc0e0474b3b5c945df287b079d2a23dc07dcc6240a7d2f18e081d",
            "font/fonts/bootstrap-icons.woff2": "cfe45b981d1b91b173361a34cfce5f60893dbd1ac4af2c3ac11fc17552c5401f",
        },
        license="LICENSE",
        license_sha256="0623348b57e817b6897c41b6065380b599d5befe2839d83270566c605e430441",
    ),
    "fontawesome": VendorLibrary(
        name="font-awesome",
        version="4.7.0",
        files={
            "css/font-awesome.min.css": "799aeb25cc0373fdee0e1b1db7ad6c2f6a0e058dfadaa3379689f583213190bd",
            "fonts/FontAwesome.otf": "444dd4366615ffc4a16d012b2fa90137065d3ccb410fa6fd5e4ddd7b5e4ffcd5",
            "fonts/fontawesome-webfont.eot": "7bfcab6db99d5cfbf1705ca0536ddc78585432cc5fa41bbd7ad0f009033b2979",
            "fonts/fontawesome-webfont.svg": "ad6157926c1622ba4e1d03d478f1541368524bfc46f51e42fe0d945f7ef323e4",
            "fonts/fontawesome-webfont.ttf": "aa58f33f239a0fb02f5c7a6c45c043d7a9ac9a093335806694ecd6d4edc0d6a8",
            "fonts/fontawesome-webfont.woff": "ba0c59deb5450f5cb41b3f93609ee2d0d995415877ddfa223e8a8a7533474f07",
            "fonts/fontawesome-webfont.woff2": "2adefcbc041e7d18fcf2d417879dc5a09997aa64d675b7a3c4b6ce33da13f3fe",
        },
        license="README.md",
        license_sha256="610427fe917f2b51ef69b5bfa9a7bfe3fcba59b1ccaf86a500a47e5fa1da322b",
    ),
    "ionrangeslider": VendorLibrary(
        name="ion-rangeslider",
        version="2.3.1",
        files={
            "css/ion.rangeSlider.css": "683c3601c8c673010044e3fbad99c8da5741fbf5f2b93c1b647e43af5222b8ca",
            "js/ion.rangeSlider.min.js": "67adfdac93b9ec1899cd00e55ac1b217e109dc5b379c3e2940f91f8a64f2dd2f",
        },
        license="License.md",
        license_sha256="eab00c5f6ec0a56b255565aa3f2e624e53e220bc916f1fab4cbdac14e051569e",
    ),
    "datatables": VendorLibrary(
        name="DataTables",
        version="1.10.22",
        base_url="https://cdn.datatables.net/{version}/",
        npm_package="datatables.net",
        files={
            "js/jquery.dataTables.min.js": "c91c904fbfbe1fcb61c4e4cb955b35e8eb303f29d97a9f757c744fc6603a978a",
            "css/jquery.dataTables.min.css": "ca31d3aa2364f2a372c1d9ed477be2b71852e7d3a98bb92476c19efe67024a48",
            "images/sort_asc.png": "595704c3f3cf4cb65c7d9c8508a99e7480e150095473faed31a07c21b13389b8",
            "images/sort_asc_disabled.png": "a65b8f4f84d6427a81c360282fc5394d51bf99dada5f159e6aa0fce3c396825c",
            "images/sort_both.png": "3e016c23ae51417382b640ae2d19eb48047532c37ad53894bd185586559ccffb",
            "images/sort_desc.png": "d08ed0e21f187dd309030d465224da8085119a15a17d616ba0e477bb50c6f10d",
            "images/sort_desc_disabled.png": "6c0f0c1b21ef6807057afc8ddc1a925d1dbd21cb11e9270ec84ff4ac40d9a3fa",
        },
        license="https://cdn.jsdelivr.net/npm/datatables.net@1.10.22/License.txt",
        license_sha256="4f6610cece9940c3bf3de202a920e7b69491e7947d968330f03db592caa456dd",
    ),
    "datatablesconditionalpaging": VendorLibrary(
        name="DataTables conditionalPaging plug-in",
        version="1.10.22",
        base_url="https://cdn.datatables.net/plug-ins/{version}/features/conditionalPaging/",
        npm_package="datatables.net-plugins",
        files={
            "dataTables.conditionalPaging.js": "336e6dd30fe2ba132c2980f057c359453c5e85ca046842717457505acdabc39c",
        },
        license="https://cdn.jsdelivr.net/npm/datatables.net-plugins@1.10.22/License.txt",
        license_sha256="46daf76193ec5496a09285dfc4c58127f68d895c4de20ded97aff6d58b452a35",
    ),
    "d3": VendorLibrary(
        name="d3",
        version="6.7.0",
        files={
            "dist/d3.min.js": "fbb8da602a76f4ed49bac3561da62d8149fa121b8fd15685bacc21355d3a3322",
        },
        license="LICENSE",
        license_sha256="0747bebeb06b10954913149be9b9a8bdf6fad3e6fdcbd9f9524e7a94c13d2cea",
    ),
    "litepicker": VendorLibrary(
        name="litepicker",
        version="2.0.12",
        files={
            "dist/litepicker.js": "7fa62995b2417110edd2dfc18d43256816f705f9107b290d758fb9c8705e3e27",
            "dist/plugins/ranges.js": "ec92df7d80691bef3d935208ddf0e0d1b4d9efc58c1b1132358c3ee47b4de48c",
            "dist/plugins/keyboardnav.js": "2f1f56813045d77aa790718fb31ce1d0da7c6e01f674ceb2d36d7137181a56f1",
        },
        license="LICENSE.md",
        license_sha256="a14d94572e372b6ec3bd884f394b43ea2e80ab068bd37a5a7cb243662b543922",
    ),
    "jstimezonedetect": VendorLibrary(
        name="jstimezonedetect",
        version="1.0.7",
        files={
            "dist/jstz.js": "4323ac38f342b0b7b1eee332e7278c67f4d01fe21c35ab03a684d49679a4feee",
        },
        license="LICENCE.txt",
        license_sha256="70e94d1525a9cfeaec737aef0d21391b8585420add847742647cf1d916957555",
    ),
    "poppins": VendorLibrary(
        name="Poppins",
        version="v20",
        base_url="https://fonts.gstatic.com/s/poppins/{version}/",
        files={
            "pxiEyp8kv8JHgFVrJJbecmNE.woff2": "478b3ab728aaa25a76c8cd8bb04addde92c43d72e643d0fdc455340b44c3f074",
            "pxiEyp8kv8JHgFVrJJnecmNE.woff2": "cb8bdeabc838774d9808eb7c4cfcea963b57855e34f84b54797076940c8e5986",
            "pxiEyp8kv8JHgFVrJJfecg.woff2": "7d93459d86585bfcdbb7e0376056226adb25821ee54b96236fe2123e9560929f",
        },
        license="https://cdn.jsdelivr.net/gh/google/fonts@7dc16b7de42db624b902f2292b68ed9e489e5053/ofl/poppins/OFL.txt",
        license_sha256="6be04893d770899a015649c7aa3b582f871b272f8747a92b78b17c3e5c8b2573",
    ),
}

# Each library's version, by key, available in templates as `js_versions`.
# Plugin templates may read the keys which the deprecated FLEXMEASURES_JS_VERSIONS setting had, such as `js_versions.vega`.
JS_VERSIONS: dict[str, str] = {
    key: library.version for key, library in VENDOR_LIBRARIES.items()
}


def local_file(key: str, path: str) -> Path:
    """Where a library's file is stored when it was fetched."""
    library = VENDOR_LIBRARIES[key]
    return VENDOR_DIR / key / library.version / path


def vendor_url(key: str, path: str) -> str:
    """URL of a library's file: served by FlexMeasures if it was fetched, or else from the library's CDN."""
    library = VENDOR_LIBRARIES[key]
    if local_file(key, path).is_file():
        return url_for(
            "flexmeasures_ui.static",
            filename=f"vendor/{key}/{library.version}/{path}",
        )
    return library.url(path)


def vendor_attrs(key: str, path: str, attribute: str = "src") -> Markup:
    """Attributes for a <script> or <link> tag that loads a library's file.

    When the file comes from a CDN, the browser checks it against its recorded hash.
    """
    url = vendor_url(key, path)
    attrs = f'{attribute}="{escape(url)}"'
    if "://" in url:
        digest = bytes.fromhex(VENDOR_LIBRARIES[key].files[path])
        attrs += f' integrity="sha256-{base64.b64encode(digest).decode()}" crossorigin="anonymous"'
    return Markup(attrs)


def missing_files() -> list[Path]:
    """Files of the libraries which were not fetched, so browsers load them from CDNs."""
    return [
        local_file(key, path)
        for key, library in VENDOR_LIBRARIES.items()
        for path in library.files
        if not local_file(key, path).is_file()
    ]


def download(url: str) -> bytes:
    # Some CDNs refuse urllib's default User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "FlexMeasures"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch(
    keys: list[str] | None = None,
    download: Callable[[str], bytes] = download,
) -> int:
    """Download the libraries' files and licences into static/vendor/, checking each against its recorded hash.

    Files that are already there with the right hash are skipped.
    Returns the number of files written.
    """
    written = 0
    for key in keys or VENDOR_LIBRARIES:
        library = VENDOR_LIBRARIES[key]
        to_fetch = [
            (path, library.url(path), sha256) for path, sha256 in library.files.items()
        ]
        to_fetch.append(
            (library.license_path, library.license_url, library.license_sha256)
        )
        for path, url, sha256 in to_fetch:
            target = local_file(key, path)
            if target.is_file() and _sha256(target.read_bytes()) == sha256:
                continue
            content = download(url)
            if _sha256(content) != sha256:
                raise ValueError(
                    f"{url} does not match the hash recorded for {key} {library.version}."
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            partial.write_bytes(content)
            partial.replace(target)
            written += 1
    return written


def print_hashes(key: str, download: Callable[[str], bytes] = download):
    """Print the hashes of a library's files at its recorded version, ready to paste into VENDOR_LIBRARIES."""
    library = VENDOR_LIBRARIES[key]
    print("files={")
    for path in library.files:
        print(f'    "{path}": "{_sha256(download(library.url(path)))}",')
    print("},")
    print(f'license_sha256="{_sha256(download(library.license_url))}",')


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
