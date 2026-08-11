"""Shared Jinja2 templates instance."""
from fastapi.templating import Jinja2Templates

from . import config

templates = Jinja2Templates(directory=str(config.BASE_DIR / "app" / "templates"))
