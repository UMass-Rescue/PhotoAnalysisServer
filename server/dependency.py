import logging
from typing import Optional

from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from pydantic import BaseModel, Field

logger = logging.getLogger("api")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Authentication Objects

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