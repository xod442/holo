"""Walter's standalone browser-desktop experience."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..web import templates

router = APIRouter()


@router.get("/walter", response_class=HTMLResponse, include_in_schema=False)
def walter_desktop(request: Request):
    """Render Walter without HOLO's application shell."""
    return templates.TemplateResponse(request, "walter.html", {"request": request})
