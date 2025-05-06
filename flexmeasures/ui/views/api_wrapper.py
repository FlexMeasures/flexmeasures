from __future__ import annotations

from typing import Any

from flask import current_app, request
from flask_security import current_user
import requests


class InternalApi(object):
    """
    Simple wrapper around the requests lib, which we use to talk to
    our actual internal JSON Api via requests. It can only be used to perform
    requests on the same URL root as the current request.
    - We use this because it is cleaner than calling the API code directly.
      That would re-use the same request we are working on here, which
      works differently in some ways like content-type and authentication.
      The Flask/Werkzeug request is also immutable, so we could not adapt the
      request anyways.
    - Also, we implement auth token handling
    - Finally we have some logic to control which error codes we want to raise.
    """

    _log_prefix = "Internal API call ― "

    def _auth_headers(self):
        return {
            "content-type": "application/json",
            "Authorization": current_user.get_auth_token(),
        }

    def _maybe_raise(
        self, response: requests.Response, do_not_raise_for: list | None = None
    ):
        """
        Raise an error in the API (4xx, 5xx) if the error code is not in the list of codes
        we want to ignore / handle explicitly.
        """
        if do_not_raise_for is None:
            do_not_raise_for = []
        if response.status_code not in do_not_raise_for:
            response.raise_for_status()

    def _url_root(self) -> str:
        """
        Get the root for the URLs this API should use to call FlexMeasures.
        """
        url_root = request.url_root
        if current_app.config.get("FLEXMEASURES_FORCE_HTTPS", False):
            # this replacement is for the case we are behind a load balancer who talks http internally
            url_root = url_root.replace("http://", "https://")
        return url_root

    def get(
        self,
        url: str,
        query: dict[str, Any] | None = None,
        do_not_raise_for: list | None = None,
    ) -> requests.Response:
        full_url = f"{self._url_root()}{url}"
        current_app.logger.debug(
            f"{self._log_prefix} Calling GET to {full_url} with query {query} ..."
        )
        response = requests.get(
            full_url,
            params=query,
            headers=self._auth_headers(),
        )
        self._maybe_raise(response, do_not_raise_for)
        return response

    def post(
        self,
        url: str,
        args: dict | None = None,
        do_not_raise_for: list | None = None,
    ) -> requests.Response:
        full_url = f"{self._url_root()}{url}"
        current_app.logger.debug(
            f"{self._log_prefix} Call POST to {full_url} with json data {args} ..."
        )
        response = requests.post(
            full_url,
            headers=self._auth_headers(),
            json=args if args else {},
        )
        self._maybe_raise(response, do_not_raise_for)
        return response

    def patch(
        self,
        url: str,
        args: dict | None = None,
        do_not_raise_for: list | None = None,
    ) -> requests.Response:
        full_url = f"{self._url_root()}{url}"
        current_app.logger.debug(
            f"{self._log_prefix} Calling PATCH to {full_url} with json data {args} ..."
        )
        response = requests.patch(
            full_url,
            headers=self._auth_headers(),
            json=args if args else {},
        )
        self._maybe_raise(response, do_not_raise_for)
        return response

    def delete(
        self,
        url: str,
        do_not_raise_for: list | None = None,
    ) -> requests.Response:
        full_url = f"{self._url_root()}{url}"
        current_app.logger.debug(f"{self._log_prefix} Calling DELETE to {full_url} ...")
        response = requests.delete(
            full_url,
            headers=self._auth_headers(),
        )
        self._maybe_raise(response, do_not_raise_for)
        return response
