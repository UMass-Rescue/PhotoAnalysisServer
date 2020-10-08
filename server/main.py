from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import os
import hashlib
import redis as rd
from rq import Queue
from rq.job import Job
from pymongo import MongoClient
import shutil
from pydantic import BaseModel, BaseSettings

from model_prediction import get_model_prediction

client = MongoClient('database', 27017)
database = client['result_database']
image_results = database['image_results']
redis = rd.Redis(host='redis', port=6379)
app = FastAPI()
prediction_queue = Queue("model_prediction", connection=redis)


class Settings(BaseSettings):
    available_models = {
        "scene_detection": 5005,
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

    # invalid_models = []
    # for model in models:
    #     if model not in settings.available_models:
    #         print(model)
    #         invalid_models.append(model)
    #
    # if invalid_models:
    #     error_message = "Invalid Models Specified: " + ''.join(invalid_models)
    #     return HTTPException(status_code=400, detail=error_message)

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
            prediction_queue.enqueue(get_model_prediction, 'host.docker.internal', 5005, file_name, job_id=image_hash)

    return {"images": [hashes[key] for key in hashes]}


@app.get("/predict")
async def get_empty_job():
    return HTTPException(status_code=404, detail="key not found")


@app.get("/predict/{key}")
async def get_job(key: str = ""):
    # Check that image exists in system
    try:
        # Fetch the job status and create a response accordingly
        job = Job.fetch(key, connection=redis)
    except:
        return HTTPException(status_code=404, detail="key not found")

    response = {}
    if "finished" == job.get_status():
        response = {"status": "SUCCEEDED", "results": job.result}
    elif "failed" == job.get_status():
        response = {"status": "FAILED", "results": job.exc_info}
    else:
        response = {"status": job.get_status()}

    return response
