import bcrypt
import constants
import jwt
import re

from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
client = MongoClient(constants.MONGO_SVR)

def generate_jwt_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, constants.SECRET_KEY, algorithm=constants.ALGORITHM)
    return encoded_jwt

def hash_password(password: str) -> str:
  salt = bcrypt.gensalt()
  return bcrypt.hashpw(password.encode('utf-8'), salt)

def verify_password(password: str, hashed: bytes) -> bool:
  return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

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

    