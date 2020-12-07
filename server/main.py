import hashlib
import logging
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import (
    Deque, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple, Union
)

import redis as rd
import requests
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from starlette import status
from jose import JWTError, jwt

from auth import SECRET_KEY, ALGORITHM, get_user, TokenData, User, Token, authenticate_user, \
    ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token, get_password_hash, add_new_user
from model_prediction import get_model_prediction
from pydantic import BaseSettings, BaseModel
from rq import Queue
from rq.job import Job

from db_connection import add_image_db, get_models_from_image_db, get_image_filename_from_hash_db, add_user_db, \
    get_user_by_name_db

logger = logging.getLogger("api")
app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# -------------------------------
# Model Queue + Model Validation/Registration
# -------------------------------

redis = rd.Redis(host='redis', port=6379)
prediction_queue = Queue("model_prediction", connection=redis)
pool = ThreadPoolExecutor(10)
WAIT_TIME = 10


class Settings(BaseSettings):
    available_models = {}


settings = Settings()

# -------------------------------
# Web Server Configuration
# -------------------------------

# Must have CORSMiddleware to enable localhost client and server
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5057",
    "http://localhost:5000",
    "http://localhost:6379",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Model(BaseModel):
    modelName: str
    modelPort: int


# -------------------------------
# Web Server Functionality
# -------------------------------


@app.get("/")
async def root():
    return {"message": "PhotoAnalysisServer Running!"}


@app.get("/models")
async def get_available_models():
    """
    Returns list of available models to the client. This list can be used when calling get_prediction,
    with the request
    """
    return {"models": [*settings.available_models]}


@app.post("/predict")
async def get_prediction(images: List[UploadFile] = File(...), models: List[str] = ()):
    """

    :param images: List of file objects that will be used by the models for prediction
    :param models: List of models to run on images
    :return: Unique keys for each image uploaded in images.
    """

    # Start with error checking on the models list.
    # Ensure that all desired models are valid.
    if not models:
        return HTTPException(status_code=400, detail="You must specify models to process images with")

    invalid_models = []
    for model in models:
        if model not in settings.available_models:
            invalid_models.append(model)

    if invalid_models:
        error_message = "Invalid Models Specified: " + ''.join(invalid_models)
        return HTTPException(status_code=400, detail=error_message)

    # Now we must hash each uploaded image
    # After hashing, we will store the image file on the server.

    buffer_size = 65536  # Read image data in 64KB Chunks for hashlib
    hashes = {}

    # Process uploaded images
    for upload_file in images:
        file = upload_file.file
        md5 = hashlib.md5()
        while True:
            data = file.read(buffer_size)
            if not data:
                break
            md5.update(data)

        # Process image
        image_hash = md5.hexdigest()
        hashes[upload_file.filename] = image_hash

        # Save files to directory ./images/ and the images will automatically be saved locally via Docker
        # The ./images/ folder on the host machine maps to ./server/images/ on Docker

        file.seek(0)  # Reset read head to beginning of file
        file_name = image_hash + os.path.splitext(upload_file.filename)[1]

        # Create empty file and copy contents of file object
        upload_folder = open("./images/" + file_name, 'wb+')
        shutil.copyfileobj(file, upload_folder)

        # Close created file
        upload_folder.close()

        # Now, we must create the image hash entry in the DB for the uploaded image.
        # If the image exists in the DB, this method will simply return.
        add_image_db(image_hash, upload_file.filename)

        for model in models:
            model_port = settings.available_models[model]
            logger.debug('Adding Job For For Image ' + image_hash + ' With Model ' + model)
            # Submit a job to use scene detection model
            prediction_queue.enqueue(get_model_prediction, 'host.docker.internal', model_port, file_name, image_hash,
                                     model,
                                     job_id=image_hash + model)

    return {"images": [hashes[key] for key in hashes]}


@app.get("/predict/{image_hash}")
async def get_job(image_hash: str = ""):
    # Check that image exists in system
    # try:
    #     # Fetch the job status and create a response accordingly
    #     job = Job.fetch(image_hash, connection=redis)
    # except:
    #     return HTTPException(status_code=404, detail="key not found")

    # Ensure that the image hash exists somewhere in our server
    if not get_models_from_image_db(image_hash) and not Job.exists(image_hash, connection=redis):
        return HTTPException(status_code=404, detail="Invalid image hash specified:" + image_hash)

    # If job is currently in the system, return the results from here.
    if Job.exists(image_hash, connection=redis) and not Job.fetch(image_hash,
                                                                  connection=redis).get_status() == 'finished':
        return {'status': 'Pending'}

    results = {
        'status': 'Finished',
        'filename': get_image_filename_from_hash_db(image_hash),
        'models': get_models_from_image_db(image_hash)
    }
    return results


def ping_model(model_name):
    """
    Periodically ping the model's service to make sure that
    it is active. If it's not, remove the model from the available_models setting
    """
    model_is_alive = True
    while model_is_alive:
        try:
            r = requests.get('http://host.docker.internal:' + str(settings.available_models[model_name]) + '/')
            r.raise_for_status()
            time.sleep(WAIT_TIME)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            settings.available_models.pop(model_name)
            model_is_alive = False
            logger.debug("Model " + model_name + " is not responsive. Removing the model from available services...")


@app.post("/register/")
async def register_model(model: Model):
    """
    Register a single model to the server by adding the model's name and port
    to available model settings. Also kick start a separate thread to keep track
    of the model service status
    """

    # Check if already registered
    if model.modelName in settings.available_models:
        return {"registered": "yes", "model": model.modelName}

    settings.available_models[model.modelName] = model.modelPort
    future = pool.submit(ping_model, model.modelName)

    # Check for connection with the model just added
    try:
        r = requests.get('http://host.docker.internal:' + str(settings.available_models[model.modelName]) + '/')
        r.raise_for_status()
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return {"registered": "no", "model": model.modelName}
    logger.debug("Add new model: " + model.modelName + " to available services")
    return {"registered": "yes", "model": model.modelName}


# -------------------------------------------------------------------------------
#
#           User Authentication Endpoints
#
# -------------------------------------------------------------------------------


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unable to validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = get_user(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user=Depends(get_current_user)):
    logger.debug('Current User Disabled:' + str(current_user['disabled']))
    if current_user['disabled']:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['username']}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post('/users/new/')
def create_account(username, password):
    return add_new_user(username, password)


@app.get("/users/me/", response_model=User)
async def read_users_me(current_user= Depends(get_current_active_user)):
    return current_user