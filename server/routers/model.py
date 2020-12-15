import hashlib
import os
import shutil
import time

from starlette import status
from starlette.responses import JSONResponse

import dependency
import requests
from fastapi import File, UploadFile, HTTPException, Depends, APIRouter
from rq.job import Job

from routers.auth import current_user_investigator
from dependency import logger, Model, settings, prediction_queue, redis, User, pool
from model_prediction import get_model_prediction
from db_connection import add_image_db, get_models_from_image_db, get_image_filename_from_hash_db, add_user_to_image, \
    get_images_from_user_db, get_image_by_md5_hash_db
from typing import (
    List
)

model_router = APIRouter()


@model_router.get("/list", dependencies=[Depends(current_user_investigator)])
async def get_available_models():
    """
    Returns list of available models to the client. This list can be used when calling get_prediction,
    with the request
    """
    return {"models": [*settings.available_models]}


@model_router.post("/predict")
async def get_prediction(images: List[UploadFile] = File(...),
                         models: List[str] = (),
                         current_user: User = Depends(current_user_investigator)):
    """

    :param current_user: User object who is logged in
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
    hashes_md5 = {}

    # Process uploaded images
    for upload_file in images:
        file = upload_file.file
        md5 = hashlib.md5()
        sha1 = hashlib.sha1()
        while True:
            data = file.read(buffer_size)
            if not data:
                break
            md5.update(data)
            sha1.update(data)

        # Process image
        hash_md5 = md5.hexdigest()
        hash_sha1 = sha1.hexdigest()
        hashes_md5[upload_file.filename] = hash_md5

        # Save files to directory ./images/ and the images will automatically be saved locally via Docker
        # The ./images/ folder on the host machine maps to ./server/images/ on Docker

        file.seek(0)  # Reset read head to beginning of file
        file_name = hash_md5 + os.path.splitext(upload_file.filename)[1]

        if get_image_by_md5_hash_db(hash_md5):
            image_object = get_image_by_md5_hash_db(hash_md5)
        else:  # If image does not already exist in db
            image_object = dependency.UniversalMLImage(**{
                'id': hash_md5,
                'file_names': [upload_file.filename],
                'hash_md5': hash_md5,
                'hash_sha1': hash_sha1,
                'hash_perceptual': '',
                'users': [current_user.username],
                'models': {}
            })


            # Create empty file and copy contents of file object
            upload_folder = open("./images/" + file_name, 'wb+')
            shutil.copyfileobj(file, upload_folder)
            upload_folder.close()  # Close created file

            # Add created image object to database
            add_image_db(image_object)

        # Associate the current user with the image that was uploaded
        add_user_to_image(image_object, current_user.username)

        for model in models:
            model_port = settings.available_models[model]
            logger.debug('Adding Job For For Image ' + hash_md5 + ' With Model ' + model)
            # Submit a job to use scene detection model
            prediction_queue.enqueue(get_model_prediction, 'host.docker.internal', model_port, file_name, hash_md5,
                                     model,
                                     job_id=hash_md5 + model)

    return {"images": [hashes_md5[key] for key in hashes_md5]}


@model_router.post("/results", dependencies=[Depends(current_user_investigator)])
async def get_job(image_hashes: List[str]):

    results = []
    logger.debug('Image Hashes')
    logger.debug(image_hashes)

    if not image_hashes:
        return []

    for image_hash in image_hashes:
        # Ensure that the image hash exists somewhere in our server
        if not get_models_from_image_db(image_hash) and not Job.exists(image_hash, connection=redis):
            results.append({'status': 'failure', 'detail': 'Unknown image hash specified: [' + image_hash + ']'})

        # If job is currently in the system, return the results from here.
        elif Job.exists(image_hash, connection=redis) and \
                not Job.fetch(image_hash, connection=redis).get_status() == 'finished':
            results.append({'status': 'failure', 'detail': 'Image Processing Pending.'})

        else:
            results.append({
                'status': 'success',
                'filename': get_image_filename_from_hash_db(image_hash),
                'models': get_models_from_image_db(image_hash)
            })
    return results


@model_router.get("/user/")
def get_images_by_user(current_user: User = Depends(current_user_investigator), page_id: int = -1):
    """
    Returns a list of image hashes of images submitted by a user. Optional pagination of image hashes
    :param current_user: User currently logged in
    :param page_id: Optional int for individual page of results (From 1...N)
    :return: List of hashes user has submitted (by page) and number of total pages. If no page is provided,
             then only the number of pages available is returned.
    """

    hashes, num_pages = get_images_from_user_db(current_user.username, page_id)

    if page_id <= 0:
        return {'status': 'success', 'num_pages': num_pages}
    elif page_id > num_pages:
        return {'status': 'failure', 'detail': 'Page does not exist.', 'num_pages': num_pages, 'current_page': page_id}

    return {'status': 'success', 'num_pages': num_pages, 'current_page': page_id, 'images': hashes}


def ping_model(model_name):
    """
    Periodically ping the model's service to make sure that
    it is active. If it's not, remove the model from the available_models setting
    """

    model_is_alive = True

    def kill_model():
        settings.available_models.pop(model_name)
        nonlocal model_is_alive
        model_is_alive = False
        logger.debug("Model " + model_name + " is not responsive. Removing the model from available services...")

    while model_is_alive and not dependency.shutdown:
        try:
            r = requests.get('http://host.docker.internal:' + str(settings.available_models[model_name]) + '/status')
            r.raise_for_status()
            for increment in range(dependency.WAIT_TIME):
                if not dependency.shutdown:  # Check between increments to stop hanging on shutdown
                    time.sleep(1)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
            kill_model()
            return

    logger.debug("Model [" + model_name + "] Healthcheck Thread Terminated.")


@model_router.post("/register/")
async def register_model(model: Model):
    """
    Register a single model to the server by adding the model's name and port
    to available model settings. Also kick start a separate thread to keep track
    of the model service status
    """

    # TODO: Implement authentication so only models can make this call

    # Do not accept calls if server is in process of shutting down
    if dependency.shutdown:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                'status': 'failure',
                'detail': 'Server is shutting down. Unable to complete new model registration.'
            }
        )

    # Do not add duplicates of running models to server
    if model.modelName in settings.available_models:
        return {
            "status": "success",
            'model': model.modelName,
            'detail': 'Model has already been registered.'
        }

    # Ensure that we can connect back to model before adding it
    try:
        r = requests.get('http://host.docker.internal:' + str(model.modelPort) + '/status')
        r.raise_for_status()
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
        return {
            "status": "failure",
            'model': model.modelName,
            'detail': 'Unable to establish successful connection to model.'
        }

    # Register model to server and create thread to ensure model is responsive
    settings.available_models[model.modelName] = model.modelPort
    pool.submit(ping_model, model.modelName)

    logger.debug("Model " + model.modelName + " successfully registered to server.")

    return {
        "status": "success",
        'model': model.modelName,
        'detail': 'Model has been successfully registered to server.'
    }
