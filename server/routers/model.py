import hashlib
import os
import shutil
import time
import string
import random
import csv
from io import StringIO

import imagehash as imagehash
from PIL import Image
from rq.registry import StartedJobRegistry
from starlette import status
from starlette.responses import JSONResponse, StreamingResponse

import dependency
import requests
from fastapi import File, UploadFile, HTTPException, Depends, APIRouter
from rq.job import Job

from routers.auth import current_user_investigator
from dependency import logger, Model, settings, prediction_queue, redis, User, pool, UniversalMLImage, APIKeyData
from db_connection import add_image_db, add_user_to_image, get_images_from_user_db, get_image_by_md5_hash_db, \
    get_api_key_by_key_db, add_filename_to_image, add_model_to_image_db, get_models_db, add_model_db
from typing import (
    List
)

model_router = APIRouter()


@model_router.get("/list", dependencies=[Depends(current_user_investigator)])
async def get_available_prediction_models():
    """
    Returns list of available models to the client. This list can be used when calling get_prediction,
    with the request
    """
    return {"models": [*settings.available_models]}


@model_router.get("/all", dependencies=[Depends(current_user_investigator)])
async def get_all_prediction_models():
    """
    Returns a list of every model that has ever been seen by the server, as well as the fields available in that model
    """
    all_models = get_models_db()
    return {'models': all_models}


@model_router.post("/predict")
def create_new_prediction_on_image(images: List[UploadFile] = File(...),
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

            # Create empty file and copy contents of image object

            uploaded_raw_file_path = "./images/" + file_name
            uploaded_raw_image = open(uploaded_raw_file_path, 'wb+')
            shutil.copyfileobj(file, uploaded_raw_image)

            # Internally, represent all images as RGB jpg. This prevents RGBA from causing negative
            # effects in some models
            if os.path.splitext(upload_file.filename)[1].lower() not in ['.jpg', '.jpeg']:
                logger.debug('Converting: ' + hash_md5)
                png = Image.open(uploaded_raw_image).convert('RGBA')
                background = Image.new('RGBA', png.size, (255, 255, 255))
                alpha_composite = Image.alpha_composite(background, png)
                file_name = hash_md5 + '.jpg'
                alpha_composite.convert('RGB').save('./images/' + file_name, 'JPEG', quality=100)
                os.remove(uploaded_raw_file_path)  # If we do conversions, remove original file
                logger.debug('Converted: ' + hash_md5)

            # Generate perceptual hash
            hash_perceptual = str(imagehash.phash(Image.open('./images/' + file_name)))

            # Create a UniversalMLImage object to store data
            image_object = UniversalMLImage(**{
                'file_names': [upload_file.filename],
                'hash_md5': hash_md5,
                'hash_sha1': hash_sha1,
                'hash_perceptual': hash_perceptual,
                'users': [current_user.username],
                'models': {}
            })

            # Add created image object to database
            add_image_db(image_object)

        # Associate the current user with the image that was uploaded
        add_user_to_image(image_object, current_user.username)

        # Associate the name the file was uploaded under to the object
        add_filename_to_image(image_object, upload_file.filename)

        for model in models:
            random_tail = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

            job_id = hash_md5 + '---' + model + '---' + random_tail

            model_port = settings.available_models[model]
            logger.debug('Adding Job For For Image ' + hash_md5 + ' With Model ' + model + ' With ID ' + job_id)
            # Submit a job to use scene detection model
            prediction_queue.enqueue(get_model_prediction, 'host.docker.internal', model_port, file_name, hash_md5,
                                     model,
                                     job_id=job_id)

    return {"images": [hashes_md5[key] for key in hashes_md5]}


@model_router.post("/results", dependencies=[Depends(current_user_investigator)])
async def get_job(md5_hashes: List[str]):
    results = []

    if not md5_hashes:
        return []

    for md5_hash in md5_hashes:

        # If there are any pending predictions, alert user and return existing ones
        # Since job_id is a composite hash+model, we must loop and find all jobs that have the
        # hash we want to find. We must get all running and pending jobs to return the correct value
        all_jobs = StartedJobRegistry('model_prediction', connection=redis).get_job_ids() + prediction_queue.job_ids

        image = get_image_by_md5_hash_db(md5_hash)  # Get image object
        found_pending_job = False
        for job_id in all_jobs:
            if md5_hash in job_id and Job.fetch(job_id, connection=redis).get_status() != 'finished':
                found_pending_job = True
                results.append({
                    'status': 'success',
                    'detail': 'Image has pending predictions. Check back later for all model results.',
                    **image.dict()
                })
                break  # Don't look for more jobs since we have found one that is pending

        # If we have found a job that is pending, then move on to next image
        if found_pending_job:
            continue

        # If we haven't found a pending job for this image, and it doesn't exist in our database, then that
        # means that the image hash must be invalid.
        if not image:
            results.append({
                'status': 'failure',
                'detail': 'Unknown md5 hash specified.',
                'hash_md5': md5_hash
            })
            continue

        # If everything is successful with image, return data
        results.append({
            'status': 'success',
            **image.dict()
        })
    return results


@model_router.post("/search/")
def search_images(
        current_user: User = Depends(current_user_investigator),
        page_id: int = -1,
        search_string: str = '',
        search_filter: dependency.SearchFilter = None,
    ):
    """
    Returns a list of image hashes of images submitted by a user. Pagination of image hashes as
    well as searching is provided by this method
    :param current_user: User currently logged in
    :param page_id: Optional int for individual page of results (From 1...N)
    :param search_filter Optional filter to narrow results by models
    :param search_string Optional string to narrow results by metadata field
    :return: List of hashes user has submitted (by page) and number of total pages. If no page is provided,
             then only the number of pages available is returned.
    """

    # Parse the search filter from the request body
    if not search_filter:
        search_filter = {}
    else:
        search_filter = search_filter.search_filter

    db_result = get_images_from_user_db(current_user.username, page_id, search_filter, search_string)
    num_pages = db_result['num_pages']
    hashes = db_result['hashes'] if 'hashes' in db_result else []
    num_images = db_result['num_images']
    page_size = dependency.PAGINATION_PAGE_SIZE

    if page_id <= 0:
        return {
            'status': 'success',
            'num_pages': num_pages,
            'page_size': page_size,
            'num_images': num_images
        }
    elif page_id > num_pages:
        return {
            'status': 'failure',
            'detail': 'Page does not exist.',
            'num_pages': num_pages,
            'page_size': page_size,
            'num_images': num_images,
            'current_page': page_id}

    return {
        'status': 'success',
        'num_pages': num_pages,
        'page_size': page_size,
        'num_images': num_images,
        'current_page': page_id,
        'hashes': hashes
    }


@model_router.post('/search/download')
def download_search_image_hashes(
        current_user: User = Depends(current_user_investigator),
        search_string: str = '',
        search_filter: dependency.SearchFilter = None
    ):
    if search_string == '' and not search_filter:
        return {
            'status': 'failure',
            'detail': 'You must specify a search string or search filter'
        }

    db_result = get_images_from_user_db(
        current_user.username,
        search_filter=search_filter.search_filter,
        search_string=search_string,
        paginate=False
    )
    hashes = db_result['hashes']

    return {
        'status': 'success',
        'hashes': hashes
    }

def get_api_key(api_key_header: str = Depends(dependency.api_key_header_auth)):
    """
    Validates an API contained in the header. For some reason, this method will ONLY function
    when in the same file as the Depends(...) check. Therefore, this is not in auth.py
    """

    api_key_data = get_api_key_by_key_db(api_key_header)
    if not api_key_data or not api_key_data.enabled:
        raise dependency.CredentialException
    return api_key_data


@model_router.post("/register/")
def register_model(model: Model
                   , api_key: APIKeyData = Depends(get_api_key)
                   ):
    """
    Register a single model to the server by adding the model's name and port
    to available model settings. Also kick start a separate thread to keep track
    of the model service status
    """

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


def get_model_prediction(host, port, filename, image_hash, model_name):
    """
    Helper method to generate prediction for a given model. This will be run in a separate thread by the
    redis queue
    """
    # Receive Prediction from Model

    args = {'filename': filename}
    try:
        request = requests.post('http://' + host + ':' + str(port) + '/predict', params=args)
        request.raise_for_status()  # Ensure model connection is successful
        if request.json()['status'] == 'success':
            model_result = request.json()['result']['result']
            model_classes = request.json()['result']['classes']
            print("\n\n\n", model_result , "\n\n\n")
        else:
            print('Failure on predicting image ' + image_hash + ' on model ' + model_name)
            return
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
        print('Fatal error when predicting image ' + image_hash + ' on model ' + model_name)
        return

    # Store result of model prediction into database
    if dependency.image_collection.find_one({"hash_md5": image_hash}):
        print('Updating Model!!')
        image_object = get_image_by_md5_hash_db(image_hash)
        add_model_to_image_db(image_object, model_name, model_result)
        add_model_db(model_name, model_classes)
    return model_result


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

    if dependency.shutdown:
        logger.debug("Model [" + model_name + "] Healthcheck Thread Terminated.")
