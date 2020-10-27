from datetime import datetime
import hashlib
import logging
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from typing import (
    Deque, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple, Union
)

import redis as rd
import requests
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from model_prediction import get_model_prediction
from pydantic import BaseSettings, BaseModel
from pymongo import MongoClient
from rq import Queue
from rq.job import Job

logger = logging.getLogger("api")
app = FastAPI()

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

# -------------------------------
# Database Models + Configuration
# -------------------------------

client = MongoClient('database', 27017)
database = client['image_result_db']
image_collection = database['images']  # Create collection for images in database


class Model(BaseModel):
    modelName: str
    modelPort: int


def create_db_image(image_hash: str):
    """
    Add a new image to the database.
    """

    if not image_collection.find_one({"_id": image_hash}):
        image_collection.insert_one({
            "_id": image_hash,
            "models": {}
        })
        print("Added!")
    else:
        print("Exists!")


def get_models_from_db_image(image_hash, model_name=""):
    projection = {
        "_id": 0,
        "models": 1
    }

    if not image_collection.find_one({"_id": image_hash}):
        return {}

    if model_name != "":
        results = image_collection.find_one({"_id": image_hash}, projection)
        return {model_name: results['models'][model_name]}
    else:
        return image_collection.find_one({"_id": image_hash}, projection)['models']


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
        create_db_image(image_hash)

        for model in models:
            model_port = settings.available_models[model]
            # Submit a job to use scene detection model
            prediction_queue.enqueue(get_model_prediction, 'host.docker.internal', model_port, file_name, image_hash,
                                     model,
                                     job_id=image_hash)

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
    if not get_models_from_db_image(image_hash) and not Job.exists(image_hash, connection=redis):
        return HTTPException(status_code=404, detail="Invalid image hash specified:"+image_hash)

    # If job is currently in the system, return the results from here.
    if Job.exists(image_hash, connection=redis) and not Job.fetch(image_hash, connection=redis).get_status() == 'finished':
        return {'status': 'Pending'}

    results = {
        'status': 'Finished',
        'models': get_models_from_db_image(image_hash)
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
