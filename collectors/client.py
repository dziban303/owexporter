"""Shared HTTP helper for all collectors."""

import math
import os


def _timeout_setting(name, default):
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive, finite number of seconds")
    return value


REQUEST_TIMEOUT_SECONDS = _timeout_setting("REQUEST_TIMEOUT_SECONDS", "5")
CHATS_REQUEST_TIMEOUT_SECONDS = _timeout_setting("CHATS_REQUEST_TIMEOUT_SECONDS", "60")


def get_json(session, base_url, path, params=None, *, read_timeout=None):
    """GET base_url+path and return parsed JSON. Raises on any HTTP/network/JSON error."""
    # A long-running export needs more read time without extending the
    # connection timeout for an unreachable server. Read timeouts measure
    # inactivity between reads, not the total response download duration.
    timeout = (
        REQUEST_TIMEOUT_SECONDS,
        REQUEST_TIMEOUT_SECONDS if read_timeout is None else read_timeout,
    )
    resp = session.get(f"{base_url}{path}", params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
