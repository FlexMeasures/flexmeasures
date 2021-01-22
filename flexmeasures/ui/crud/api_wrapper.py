from typing import Optional, List, Dict, Any

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
        self, response: requests.Response, do_not_raise_for: Optional[List] = None
    ):
        """
        Raise an error in the API (4xx, 5xx) if the error code is not in the list of codes
        we want to ignore / handle explicitly.
        """
        if do_not_raise_for is None:
            do_not_raise_for = []
        if response.status_code not in do_not_raise_for:
            response.raise_for_status()

    def get(
        self,
        url: str,
        query: Optional[Dict[str, Any]] = None,
        do_not_raise_for: Optional[List] = None,
    ) -> requests.Response:
        current_app.logger.debug(
            f"{self._log_prefix} GETting {url} with query {query} ..."
        )
        response = requests.get(
            f"{request.url_root}{url}",
            params=query,
            headers=self._auth_headers(),
        )
        self._maybe_raise(response, do_not_raise_for)
        return response

    def post(
        self,
        url: str,
        args: Optional[dict] = None,
        do_not_raise_for: Optional[List] = None,
    ) -> requests.Response:
        current_app.logger.debug(
            f"{self._log_prefix} POSTing {url} with json data {args} ..."
        )
        response = requests.post(
            f"{request.url_root}{url}",
            headers=self._auth_headers(),
            json=args if args else {},
        )
        self._maybe_raise(response, do_not_raise_for)
        return response

    def patch(
        self,
        url: str,
        args: Optional[dict] = None,
        do_not_raise_for: Optional[List] = None,
    ) -> requests.Response:
        current_app.logger.debug(
            f"{self._log_prefix} PATCHing {url} with json data {args} ..."
        )
        response = requests.patch(
            f"{request.url_root}{url}",
            headers=self._auth_headers(),
            json=args if args else {},
        )
        self._maybe_raise(response, do_not_raise_for)
        return response

    def delete(
        self,
        url: str,
        do_not_raise_for: Optional[List] = None,
    ) -> requests.Response:
        current_app.logger.debug(f"{self._log_prefix} DELETEing {url} ...")
        response = requests.delete(
            f"{request.url_root}{url}",
            headers=self._auth_headers(),
        )
        self._maybe_raise(response, do_not_raise_for)
        return response
