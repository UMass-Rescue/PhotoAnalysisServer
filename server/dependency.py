import logging
from concurrent.futures.thread import ThreadPoolExecutor
from enum import Enum
from typing import Optional, List

from fastapi.security import OAuth2PasswordBearer
from fastapi.security import APIKeyHeader
from passlib.context import CryptContext
from pydantic import BaseModel, BaseSettings
from pymongo import MongoClient

from rq import Queue
import redis as rd

logger = logging.getLogger("api")


# --------------------------------------------------------------------------------
#                                  Database Objects
# --------------------------------------------------------------------------------


client = MongoClient('database', 27017)
database = client['server_database']
image_collection = database['images']  # Create collection for images in database
user_collection = database['users']  # Create collection for users in database
api_key_collection = database['api_key']  # Create collection for API keys in database
model_collection = database['models']

PAGINATION_PAGE_SIZE = 15

# --------------------------------------------------------------------------------
#                                  Model Objects
# --------------------------------------------------------------------------------


class Settings(BaseSettings):
    available_models = {}


settings = Settings()


pool = ThreadPoolExecutor(10)
WAIT_TIME = 10
shutdown = False  # Signal used to shutdown running threads on restart

# Redis Queue for model-prediction jobs
redis = rd.Redis(host='redis', port=6379)
prediction_queue = Queue("model_prediction", connection=redis)


class UniversalMLImage(BaseModel):
    file_names: List[str] = []  # List of all file names that this is uploaded as
    hash_md5: str  # Image md5 hash
    hash_sha1: str  # Image sha1 hash
    hash_perceptual: str  # Image perceptual hash
    users: list = []  # All users who have uploaded the image
    models: dict = {}  # ML Model results


class Model(BaseModel):
    modelName: str
    modelPort: int


# --------------------------------------------------------------------------------
#                             Authentication Objects
# --------------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
api_key_header_auth = APIKeyHeader(name='api_key', auto_error=False)


class ExternalServices(Enum):
    predict_microservice = 'predict'
    dataset_microservice = 'dataset'
    train_microservice = 'train'


class Roles(Enum):
    admin = 'admin'
    investigator = 'investigator'
    researcher = 'researcher'


class APIKeyData(BaseModel):
    key: str
    type: str
    user: str
    detail: Optional[str] = ""
    enabled: bool


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class User(BaseModel):
    username: str
    password: str
    roles: list
    agency: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: bool = False


class CredentialException(Exception):
    pass
