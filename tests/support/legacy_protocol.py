"""The protocol's HTTP root on a test server, including a server released before the protocol
was renamed to Chargewire (Hardcharger 2.2.0 and older), which serves it only under its old
root. The driver finds the root by itself; this is for the tests that call the server's HTTP
API directly. This file is the only place that knows the old root.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

CURRENT_ROOT = "/chargewire"
CURRENT_PROTOCOL = "chargewire"
_LEGACY_ROOT = "/warp"
_LEGACY_PROTOCOL = "warp-sql"


def _discovery(url: str, context: ssl.SSLContext) -> dict:
    """The discovery document at ``url``, or ``{}`` when nothing is there (404)."""
    try:
        with urllib.request.urlopen(url=url, context=context, timeout=10) as response:
            return json.load(fp=response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {}
        raise


def api_root(base_url: str, context: ssl.SSLContext) -> str:
    """The server's versioned API root (``/chargewire/v1``): the current one when discovery at
    ``/chargewire`` announces Chargewire, else the old one when the old discovery document
    announces the protocol under its old name. Neither: the test fails."""
    if _discovery(url=base_url + CURRENT_ROOT, context=context).get("protocol") == CURRENT_PROTOCOL:
        return CURRENT_ROOT + "/v1"
    if _discovery(url=base_url + _LEGACY_ROOT, context=context).get("protocol") == _LEGACY_PROTOCOL:
        return _LEGACY_ROOT + "/v1"
    raise AssertionError(f"{base_url} does not serve the Chargewire protocol")
