"""URL helpers that respect HOLO_ROOT_PATH (the subpath behind the HPE edge).

Behind the edge the proxy strips the prefix before the app sees it, so routes
match unprefixed paths — but every URL we hand back to the browser (redirect
Location headers, template links) must include the prefix or it resolves at the
edge root and 404s. These helpers add the prefix to outgoing paths.
"""
from fastapi.responses import RedirectResponse
from starlette import status as _status

from . import config


def prefixed(path: str) -> str:
    """Prepend ROOT_PATH to a root-absolute path (leaves others untouched)."""
    if path.startswith("/"):
        return f"{config.ROOT_PATH}{path}"
    return path


def redirect(path: str, status_code: int = _status.HTTP_303_SEE_OTHER) -> RedirectResponse:
    return RedirectResponse(prefixed(path), status_code=status_code)
