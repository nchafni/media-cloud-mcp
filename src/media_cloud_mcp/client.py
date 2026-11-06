"""Access to the Media Cloud API: lazy clients, error translation, JSON-safe results."""

import datetime as dt
import os
import threading
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import mediacloud.api
import mediacloud.error
import requests
from mcp.server.mcpserver.exceptions import ToolError

ApiT = TypeVar("ApiT", bound=mediacloud.api.BaseApi)
P = ParamSpec("P")
R = TypeVar("R")

API_KEY_ENV_VAR = "MC_API_KEY"
_MAX_DETAIL_CHARS = 500

_lock = threading.Lock()
_clients: dict[type, Any] = {}


def _get_client(api_class: type[ApiT]) -> ApiT:
    # Created on first use so the server can start and list its tools without a key.
    # Sync tools run on worker threads, and each client carries its own rate limiter,
    # so there must be exactly one of each.
    with _lock:
        if api_class not in _clients:
            api_key = os.environ.get(API_KEY_ENV_VAR, "").strip()
            if not api_key:
                raise ToolError(
                    f"{API_KEY_ENV_VAR} is not set. Add a Media Cloud API key to this server's "
                    "environment. The key is on your profile page at "
                    "https://search.mediacloud.org."
                )
            _clients[api_class] = api_class(api_key)
        return _clients[api_class]


def get_search_api() -> mediacloud.api.SearchApi:
    return _get_client(mediacloud.api.SearchApi)


def get_directory_api() -> mediacloud.api.DirectoryApi:
    return _get_client(mediacloud.api.DirectoryApi)


def reset_clients() -> None:
    """Forget cached clients, so the next call rereads the API key."""
    with _lock:
        _clients.clear()


def to_jsonable(value: Any) -> Any:
    """Convert the date objects the client library puts in its results to ISO strings."""
    if isinstance(value, dt.date):  # also matches datetime
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    return value


def _describe_api_error(error: mediacloud.error.APIResponseError) -> str:
    status = error.response.status_code
    detail = str(error.data.get("note") or error.data.get("detail") or "")[:_MAX_DETAIL_CHARS]
    suffix = f" Server said: {detail}" if detail else ""

    if status in (401, 403):
        return (
            f"Media Cloud refused the request (HTTP {status}). Check that {API_KEY_ENV_VAR} is "
            f"valid and that your account may use this feature.{suffix}"
        )
    if status == 404:
        return f"Media Cloud has no such item (HTTP 404).{suffix}"
    if status == 429:
        return (
            "Media Cloud's rate limit or API quota was reached (HTTP 429). Wait and retry. "
            f"The quota resets weekly.{suffix}"
        )
    if 400 <= status < 500:
        return (
            f"Media Cloud rejected the request (HTTP {status}). Check the query syntax and "
            f"parameters; see the mediacloud://query-guide resource.{suffix}"
        )
    return f"Media Cloud returned an error (HTTP {status}). Try again later.{suffix}"


def translate_errors(func: Callable[P, R]) -> Callable[P, R]:
    """Turn expected API failures into ToolErrors, which the model gets to read.

    Any other exception reaches the model only as a generic "Error executing tool".
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except mediacloud.error.APIResponseError as error:
            raise ToolError(_describe_api_error(error)) from error
        except requests.Timeout as error:
            raise ToolError(
                "Media Cloud timed out. Try a narrower date range or fewer collections."
            ) from error
        except requests.RequestException as error:
            raise ToolError(f"Could not reach Media Cloud: {type(error).__name__}.") from error

    return wrapper
