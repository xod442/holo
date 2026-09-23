"""Single sign-on hand-off with FOCUS (same host, separate app/DB):
- incoming: verify a short-lived signed token FOCUS generated (the user's
  own email) and log them into HOLO if a matching account exists.
- outgoing: generate the same kind of token for the current HOLO user and
  redirect to FOCUS's own accepting route.
"""
import secrets
from urllib.parse import quote, urlencode

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from fastapi import APIRouter, Depends, Header, Request, status as fastapi_status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette import status

from .. import audit, config
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..security import verify_password

router = APIRouter()


class VistaCredentials(BaseModel):
    email: str
    password: str


def _serializer() -> URLSafeTimedSerializer:
    # Built fresh on each use (not at import time) so it always reflects the
    # current config.SSO_SHARED_SECRET.
    return URLSafeTimedSerializer(config.SSO_SHARED_SECRET or "unused", salt=config.SSO_SALT)


def _login_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(f"/login?error={quote(message)}", status_code=status.HTTP_303_SEE_OTHER)


def _load_token(token: str) -> dict | None:
    try:
        return _serializer().loads(token, max_age=config.SSO_TOKEN_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None


@router.post("/sso/vista/authenticate", include_in_schema=False)
def authenticate_for_vista(
    credentials: VistaCredentials,
    x_vista_auth: str = Header(""),
    db: Session = Depends(get_db),
):
    """Verify HOLO credentials for VISTA-2 without exposing HOLO's database."""
    if (
        not config.VISTA_AUTH_SECRET
        or not secrets.compare_digest(x_vista_auth, config.VISTA_AUTH_SECRET)
        or not config.SSO_SHARED_SECRET
    ):
        return JSONResponse({"detail": "Not found"}, status_code=fastapi_status.HTTP_404_NOT_FOUND)

    email = credentials.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(credentials.password, user.password_hash):
        audit.log(
            db,
            None,
            "sso.vista_login_failed",
            target_type="user",
            target_label=email,
        )
        return JSONResponse(
            {"detail": "Invalid email or password"},
            status_code=fastapi_status.HTTP_401_UNAUTHORIZED,
        )
    if user.must_change_password:
        return JSONResponse(
            {"detail": "Change your password in HOLO before signing in to VISTA-2"},
            status_code=fastapi_status.HTTP_403_FORBIDDEN,
        )

    token = _serializer().dumps({"email": user.email, "role": user.role})
    audit.log(
        db,
        user,
        "sso.vista_authenticate",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
    )
    return {"token": token}


@router.get("/sso/vista")
def sso_from_vista(request: Request, token: str = "", db: Session = Depends(get_db)):
    """Establish the HOLO session, then continue through FOCUS back to VISTA-2."""
    if not config.SSO_SHARED_SECRET:
        return _login_redirect("Single sign-on from VISTA-2 is not enabled on this server.")
    payload = _load_token(token) if token else None
    if payload is None:
        return _login_redirect("Invalid or expired sign-on token.")

    email = (payload.get("email") or "").strip().lower()
    user = db.query(User).filter(User.email == email).first() if email else None
    if user is None:
        return _login_redirect(f"No HOLO account exists for {email or 'that address'}.")

    request.session["user_id"] = user.id
    audit.log(
        db,
        user,
        "sso.login_from_vista",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
    )

    callback = f"{config.VISTA_BASE_URL}/auth/callback?{urlencode({'token': token})}"
    focus_query = urlencode({"token": token, "next": callback})
    return RedirectResponse(
        f"{config.FOCUS_BASE_URL}/sso/holo?{focus_query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/sso/focus")
def sso_from_focus(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not config.SSO_SHARED_SECRET:
        return _login_redirect("Single sign-on from FOCUS is not enabled on this server.")
    if not token:
        return _login_redirect("Missing sign-on token.")

    try:
        payload = _serializer().loads(token, max_age=config.SSO_TOKEN_MAX_AGE)
    except SignatureExpired:
        return _login_redirect("That sign-on link expired — go back to FOCUS and try again.")
    except BadSignature:
        return _login_redirect("Invalid sign-on token.")

    email = (payload.get("email") or "").strip().lower()
    user = db.query(User).filter(User.email == email).first() if email else None
    if user is None:
        return _login_redirect(f"No HOLO account exists for {email or 'that address'}.")

    request.session["user_id"] = user.id
    audit.log(db, user, "sso.login_from_focus", target_type="user", target_id=user.id,
              target_label=user.email)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/go/focus")
def go_to_focus(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not config.SSO_SHARED_SECRET:
        # Not configured on this deployment — nothing to hand off to.
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    token = _serializer().dumps({"email": user.email})
    audit.log(db, user, "sso.launch_focus", target_type="user", target_id=user.id,
              target_label=user.email)
    return RedirectResponse(
        f"{config.FOCUS_BASE_URL}/sso/holo?token={token}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
