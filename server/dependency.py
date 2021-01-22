import logging
from concurrent.futures.thread import ThreadPoolExecutor
from enum import Enum
from typing import Optional, List

from fastapi.security import OAuth2PasswordBearer
from fastapi.security import APIKeyHeader
from passlib.context import CryptContext
from pydantic import BaseModel, BaseSettings, typing, Field
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
model_collection = database['models']  # Create collection for models and their structures in database
training_collection = database['training']  # Create collection for training status and results

PAGINATION_PAGE_SIZE = 15


# --------------------------------------------------------------------------------
#                                  Model Objects
# --------------------------------------------------------------------------------


class Settings(BaseSettings):
    available_models = {}
    available_datasets = {}


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
    metadata: str = ''  # All image information stored as a string
    models: dict = {}  # ML Model results


class MicroserviceConnection(BaseModel):
    name: str = Field(alias="modelName")
    port: int = Field(alias="modelPort")

    class Config:
        allow_population_by_field_name = True


class SearchFilter(BaseModel):
    search_filter: dict


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


# --------------------------------------------------------------------------------
#                         Dataset + Training Objects
# --------------------------------------------------------------------------------

class TrainingResult(BaseModel):
    dataset: str  # Name of dataset model is being trained on
    training_id: str  # Unique training ID to track job
    username: str  # User associated with this training
    complete: bool = False  # Whether training result is complete from server
    training_accuracy: float = -1
    validation_accuracy: float = -1
    training_loss: float = -1
    validation_loss: float = -1


class TrainingRequestHttpBody(BaseModel):
    dataset: str
    model_structure: str  # Stringified JSON object of model structure
    loss_function: str
    optimizer: str
    n_epochs: int
    seed: int = 123
    split: float = 0.2
    batch_size: int = 32


class TrainingResultHttpBody(BaseModel):
    dataset_name: str
    training_id: str
    results: typing.Any
