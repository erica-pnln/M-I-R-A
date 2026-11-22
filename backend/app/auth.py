from fastapi import Header, HTTPException

from .db import sb


def _user_id(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer ") or sb is None:
        return None
    try:
        res = sb.auth.get_user(authorization.split(" ", 1)[1])
        return res.user.id if res and res.user else None
    except Exception:
        return None


def optional_user(authorization: str | None = Header(default=None)) -> str | None:
    return _user_id(authorization)


def require_user(authorization: str | None = Header(default=None)) -> str:
    uid = _user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return uid
