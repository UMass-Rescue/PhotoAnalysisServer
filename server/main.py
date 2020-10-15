import hashlib
import os
import shutil
from typing import List

import requests
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, BaseSettings
from pymongo import MongoClient
from rq import Queue
from rq.job import Job

import redis as rd
from model_prediction import get_model_prediction

client = MongoClient('database', 27017)
database = client['result_database']
image_results = database['image_results']
redis = rd.Redis(host='redis', port=6379)
app = FastAPI()
prediction_queue = Queue("model_prediction", connection=redis)


class Settings(BaseSettings):
    available_models = {
        "scene_detection": 5004,
        'example_model': 5005,
        "coke_detection": 5006,
    }


class ImageResult(BaseModel):
    fileName: str
    hash: str
    result: str


settings = Settings()

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


@app.get("/")
async def root():
    return {"message": "PhotoAnalysisServer Running!"}


@app.on_event("startup")
def validate_models():
    """
    Validate all model microservice templates provided in the settings.available_models dictionary. If a model is
    found to not be running at the expected port, then the model will be removed from the list of available models
    for the duration of the server running.
    """
    for model_name in list(settings.available_models.keys()):
        try:
            r = requests.get('http://host.docker.internal:' + str(settings.available_models[model_name]) + '/')
            r.raise_for_status()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            settings.available_models.pop(model_name)
            continue

        # If we have reached this point, then the model is accessible
        # This POST request will initialize the files in the model and prepare it for prediction
        requests.post('http://host.docker.internal:' + str(settings.available_models[model_name]) + '/status')


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

        for model in models:
            model_port = settings.available_models[model]
            # Submit a job to use scene detection model
            prediction_queue.enqueue(get_model_prediction, 'host.docker.internal', model_port, file_name,
                                     job_id=image_hash)

    return {"images": [hashes[key] for key in hashes]}


@app.get("/predict/{key}")
async def get_job(key: str = ""):
    # Check that image exists in system
    try:
        # Fetch the job status and create a response accordingly
        job = Job.fetch(key, connection=redis)
    except:
        return HTTPException(status_code=404, detail="key not found")

    if "finished" == job.get_status():
        response = {"status": "SUCCEEDED", "results": job.result}
    elif "failed" == job.get_status():
        response = {"status": "FAILED", "results": job.exc_info}
    else:
        response = {"status": job.get_status()}

    return response
