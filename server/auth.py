import datetime

from passlib.context import CryptContext
from pydantic import BaseModel, Field
from typing import Optional
from jose import JWTError, jwt
from db_connection import get_user_by_name_db, add_user_db

# to get a string like this run: openssl rand -hex 32
SECRET_KEY = "22013516088ae490602230e8096e61b86762f60ba48a535f0f0e2af32e87decd"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 180

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class User(BaseModel):
    id: int = Field(..., alias='_id')
    username: str
    password: str
    roles: list
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: bool = False


def add_new_user(username, password, roles=None):
    if not roles:
        roles = []

    result = add_user_db(username, get_password_hash(password), roles)
    return result


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def get_user(username: str):
    return get_user_by_name_db(username)


def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user:
        return False
    if not verify_password(password, user['password']):
        return False
    return user


def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


