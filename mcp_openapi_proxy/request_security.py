"""Fail-closed outbound redirect policy for OpenAPI tool execution.

An API operation is authorized against an initial URL only. Redirects, even
same-origin redirects, can change the method or target after authorization.
Never implicitly forward configured or custom credential headers on a 3xx.
"""

import requests


class RedirectRefused(requests.exceptions.RequestException):
    """A recognized redirect-policy failure with no upstream data."""


def request_no_redirect(**kwargs):
    """Send exactly one HTTP request, never follow a redirect.

    Only the original, pre-validated URL is permitted. Explicitly forbid
    overriding redirect handling, and fail closed when the response has no
    valid HTTP status. Redirects are errors even though Requests'
    raise_for_status() treats 3xx as successful.
    """
    if "allow_redirects" in kwargs:
        raise ValueError("Redirect policy cannot be overridden")

    response = requests.request(allow_redirects=False, **kwargs)
    status = getattr(response, "status_code", None)
    if type(status) is not int or status < 100 or status > 599:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise requests.exceptions.RequestException("Invalid upstream HTTP response")

    if 300 <= status < 400:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        # Do not reflect the Location or URL: either could contain credentials.
        raise RedirectRefused("Upstream redirect refused")
    return response
