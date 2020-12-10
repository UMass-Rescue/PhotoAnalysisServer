import logging
from typing import Optional

from fastapi import HTTPException
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from pydantic import BaseModel, Field, BaseSettings
from pymongo import MongoClient
from starlette import status

from rq import Queue
import redis as rd

logger = logging.getLogger("api")


# Database Objects

client = MongoClient('database', 27017)
database = client['server_database']
image_collection = database['images']  # Create collection for images in database
user_collection = database['users']  # Create collection for users in database

PAGINATION_PAGE_SIZE = 12

# Model Objects


class Settings(BaseSettings):
    available_models = {}


settings = Settings()

redis = rd.Redis(host='redis', port=6379)
prediction_queue = Queue("model_prediction", connection=redis)


class Model(BaseModel):
    modelName: str
    modelPort: int


# Authentication Objects

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
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


credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Unable to validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)