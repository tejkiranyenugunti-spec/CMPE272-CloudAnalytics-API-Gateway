import bcrypt
from app import constants
import jwt
import re

from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
client = MongoClient(constants.MONGO_SVR)

def generate_jwt_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        constants.SECRET_KEY,
        algorithm=constants.ALGORITHM
    )
    return encoded_jwt

def validate_jwt(token: str) -> bool:
    """
    Decode and validate a JWT. Returns True if valid; raises on error.
    """
    try:
        payload = jwt.decode(
            token,
            constants.SECRET_KEY,
            algorithms=[constants.ALGORITHM],
        )
        username = payload.get("user")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload missing 'user'",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return True
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def hash_password(password: str) -> str:
    """Return bcrypt hash as UTF-8 string (easier to store)."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(password: str, hashed) -> bool:
    """
    Accept hash as bytes or str. Convert appropriately and check.
    """
    if isinstance(hashed, str):
        hashed_bytes = hashed.encode("utf-8")
    else:
        hashed_bytes = hashed  # already bytes
    return bcrypt.checkpw(password.encode("utf-8"), hashed_bytes)

def authenticate_user(username: str, password: str) -> bool:
    try:
        db = client.get_database("CloudAnalytics")
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"username": username})
        if user and verify_password(password, user['password']):
            return True
        else:
            return False
    except Exception as e:
        raise Exception("Unable to find the document due to the following error: ", e)

def sanitize_login_input(username_input: str, password_input: str) -> tuple[str, str]:
    return sanitize_input(username_input), sanitize_password(password_input)

def sanitize_input(user_input):
    return re.sub(r'[^\w]', '', user_input)

def sanitize_password(user_input):
    return re.sub(r'[^\w@#$%^&+=]', '', user_input)

# ---------- Auth dependency for protected routes ----------
def require_auth(token: str = Depends(oauth2_scheme)) -> None:
    """
    Enforces Bearer auth for protected routes.
    """
    validate_jwt(token)
