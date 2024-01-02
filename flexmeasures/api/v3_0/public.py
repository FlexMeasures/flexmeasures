from operator import itemgetter
import re
import six

from flask import current_app, request
from flask_classful import FlaskView, route
from flask_json import as_json

from flexmeasures.api.common.responses import request_processed


class ServicesAPI(FlaskView):

    route_base = "/api/v3_0"
    trailing_slash = False

    @route("", methods=["GET"])
    @as_json
    def index(self):
        """API endpoint to get a service listing for this version.

        .. :quickref: Public; Obtain a service listing for this version

        :resheader Content-Type: application/json
        :status 200: PROCESSED
        """
        services = []
        for rule in current_app.url_map.iter_rules():
            url = rule.rule
            if url.startswith(self.route_base):
                methods: str = "/".join(
                    [m for m in rule.methods if m not in ("OPTIONS", "HEAD")]
                )
                stripped_url = removeprefix(url, self.route_base)
                full_url = (
                    removesuffix(request.url_root, "/") + url
                    if url.startswith("/")
                    else request.url_root + url
                )
                quickref = quickref_directive(
                    current_app.view_functions[rule.endpoint].__doc__
                )
                services.append(
                    dict(
                        url=full_url,
                        name=f"{methods} {stripped_url}",
                        description=quickref,
                    )
                )
        response = dict(
            services=sorted(services, key=itemgetter("url")),
            version="3.0",
        )

        d, s = request_processed()
        return dict(**response, **d), s


def quickref_directive(content):
    """Adapted from sphinxcontrib/autohttp/flask_base.py:quickref_directive."""
    rcomp = re.compile(r"^\s*.. :quickref:\s*(?P<quick>.*)$")

    if isinstance(content, six.string_types):
        content = content.splitlines()
    description = ""
    for line in content:
        qref = rcomp.match(line)
        if qref:
            quickref = qref.group("quick")
            parts = quickref.split(";", 1)
            if len(parts) > 1:
                description = parts[1].lstrip(" ")
            else:
                description = quickref
            break

    return description


def removeprefix(text: str, prefix: str) -> str:
    """Remove a prefix from a text.

    todo: use text.removeprefix(prefix) instead of this method, after dropping support for Python 3.8
          See https://docs.python.org/3.9/library/stdtypes.html#str.removeprefix
    """
    if text.startswith(prefix):
        return text[len(prefix) :]
    else:
        return text


def removesuffix(text: str, suffix: str) -> str:
    """Remove a suffix from a text.

    todo: use text.removesuffix(suffix) instead of this method, after dropping support for Python 3.8
        See https://docs.python.org/3.9/library/stdtypes.html#str.removesuffix
    """
    if text.endswith(suffix):
        return text[: -len(suffix)]
    else:
        return text
