from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme),
                     db: Session = Depends(get_db)) -> models.User:
    """Resolve the calling user from their bearer token."""
    payload = decode_access_token(token)
    if payload is None:
        raise CREDENTIALS_ERROR

    subject = payload.get("sub")
    if subject is None:
        raise CREDENTIALS_ERROR

    user = db.get(models.User, int(subject))
    if user is None:
        raise CREDENTIALS_ERROR
    return user


def require_technician(user: models.User = Depends(get_current_user)) -> models.User:
    """Allow technicians and managers only."""
    if user.role not in ("technician", "manager"):
        raise HTTPException(status_code=403,
                            detail="Requires technician privileges")
    return user


def require_manager(user: models.User = Depends(get_current_user)) -> models.User:
    """Allow managers only."""
    if user.role != "manager":
        raise HTTPException(status_code=403,
                            detail="Requires manager privileges")
    return user

from fastapi import Request

COOKIE_NAME = "access_token"


def get_web_user(request: Request,
                 db: Session = Depends(get_db)) -> models.User:
    """Resolve the user from a session cookie, for browser pages.

    Redirects to the login page instead of returning 401, because a
    human in a browser needs a page, not a JSON error.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    payload = decode_access_token(token)
    if payload is None or payload.get("sub") is None:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    user = db.get(models.User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user


def require_web_technician(user: models.User = Depends(get_web_user)) -> models.User:
    if user.role not in ("technician", "manager"):
        raise HTTPException(status_code=403, detail="Requires technician privileges")
    return user