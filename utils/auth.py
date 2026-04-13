"""
Authentication utilities: password hashing, JWT token management.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-please-change")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_token(user_id: int, email: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── DB-backed login ───────────────────────────────────────────────────────────

def authenticate_user(db, email: str, password: str):
    """Return User object if credentials valid, else None."""
    from utils.models import User
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if user and verify_password(password, user.password_hash):
        return user
    return None


def get_user_by_id(db, user_id: int):
    from utils.models import User
    return db.query(User).filter(User.id == user_id).first()


# ── Streamlit session helpers ─────────────────────────────────────────────────

def login_user(st, user) -> None:
    """Store user info in Streamlit session state."""
    st.session_state["logged_in"] = True
    st.session_state["user_id"] = user.id
    st.session_state["user_name"] = user.name
    st.session_state["user_email"] = user.email
    st.session_state["user_role"] = user.role
    st.session_state["token"] = create_token(user.id, user.email, user.role)


def logout_user(st) -> None:
    for key in ["logged_in", "user_id", "user_name", "user_email", "user_role", "token"]:
        st.session_state.pop(key, None)


def is_logged_in(st) -> bool:
    return st.session_state.get("logged_in", False)


def require_login(st):
    """Redirect to login if not authenticated."""
    if not is_logged_in(st):
        st.error("Please log in to access this page.")
        st.stop()


def require_role(st, *roles):
    """Stop page rendering if user doesn't have required role."""
    require_login(st)
    if st.session_state.get("user_role") not in roles:
        st.error(f"Access denied. Required roles: {', '.join(roles)}")
        st.stop()
