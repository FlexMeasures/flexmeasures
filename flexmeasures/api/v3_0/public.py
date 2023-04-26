from operator import itemgetter

from flask import current_app, request
from flask_classful import FlaskView, route
from flask_json import as_json

from flexmeasures.api.common.responses import request_processed
from flexmeasures.api.common.utils.decorators import as_response_type


class ServicesAPI(FlaskView):

    route_base = "/api/v3_0"
    trailing_slash = False

    @route("/getService", methods=["GET"])
    @as_response_type("GetServiceResponse")
    @as_json
    def get_service(self):
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
                stripped_url = url.lstrip(self.route_base)
                full_url = (
                    request.url_root.rstrip("/") + url
                    if url.startswith("/")
                    else request.url_root + url
                )
                services.append(
                    dict(
                        url=full_url,
                        name=f"{methods} {stripped_url}",
                        description=current_app.view_functions[
                            rule.endpoint
                        ].__doc__.split("\n")[0],
                    )
                )
        response = dict(
            services=sorted(services, key=itemgetter("url")),
            version="3.0",
        )

        d, s = request_processed()
        return dict(**response, **d), s
