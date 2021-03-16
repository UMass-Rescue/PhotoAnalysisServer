import hashlib
import os
import shutil
import time
import string
import random

import imagehash as imagehash
from PIL import Image
from rq.registry import StartedJobRegistry
from starlette import status
from starlette.responses import JSONResponse

import dependency
import requests
from fastapi import File, UploadFile, HTTPException, Depends, APIRouter
from rq.job import Job

from routers.auth import current_user_investigator
from dependency import logger, MicroserviceConnection, settings, prediction_queue, redis, User, pool, UniversalMLImage, \
    APIKeyData
from db_connection import add_image_db, add_user_to_image, get_images_from_user_db, get_image_by_md5_hash_db, \
    get_api_key_by_key_db, add_filename_to_image, add_model_to_image_db, get_models_db, add_model_db, \
    update_tags_to_image, update_role_to_tag_image
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


@model_router.post("/tag/update")
async def update_image_tags(md5_hashes: List[str], username: str, remove_tags: List[str] = [], new_tags: List[str] = []):
    """
    Find an image and add tags into its universalMLimage object "tags" field

    param: username
    request body(JSON): md5_hashes, remove_tags, new_tags
    """
    result = update_tags_to_image(md5_hashes, username, remove_tags, new_tags)
    return result


@model_router.post("/tag/role/update")
async def update_image_tag_roles(md5_hashes: List[str], username: str, remove_roles: List[str] = [], new_roles: List[str] = []):
    """
    Find an image and add roles_able_to_tag into its universalMLimage object "user_role_able_to_tag" field, so that role can update 
    that image's tags

    param: username
    request body(JSON): md5_hashes, remove_roles, new_roles
    """
    result = update_role_to_tag_image(md5_hashes, username, remove_roles, new_roles)
    return result




# TODO: added new param tags, needs to update code that calls this api
@model_router.post("/predict")
def create_new_prediction_on_image(images: List[UploadFile] = File(...),
                                   models: List[str] = (),
                                   current_user: User = Depends(current_user_investigator),
                                   tags: List[str] = ()):
    """
    Create a new prediction request for any number of images on any number of models. This will enqueue the jobs
    and a worker will process them and get the results. Once this is complete, a user may later query the job
    status by the unique key that is returned from this method for each image uploaded.

    :param current_user: User object who is logged in
    :param images: List of file objects that will be used by the models for prediction
    :param models: List of models to run on images
    :param tags: List of tags that user assaigned to the upload image
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

        if get_image_by_md5_hash_db(hash_md5):
            image_object = get_image_by_md5_hash_db(hash_md5)
        else:  # If image does not already exist in db

            # Generate perceptual hash
            hash_perceptual = str(imagehash.phash(Image.open('/app/images/' + file_name)))

            # Create a UniversalMLImage object to store data
            image_object = UniversalMLImage(**{
                'file_names': [upload_file.filename],
                'hash_md5': hash_md5,
                'hash_sha1': hash_sha1,
                'hash_perceptual': hash_perceptual,
                'users': [current_user.username],
                'models': {},
                'tags': tags,
                'user_role_able_to_tag': [current_user.username]
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

            model_socket = settings.available_models[model]
            logger.debug('Adding Job For For Image ' + hash_md5 + ' With Model ' + model + ' With ID ' + job_id)
            # Submit a job to use scene detection model
            prediction_queue.enqueue(get_model_prediction, model_socket, hash_md5,
                                     model, upload_file,
                                     job_id=job_id)

    return {"images": [hashes_md5[key] for key in hashes_md5]}


@model_router.post("/results", dependencies=[Depends(current_user_investigator)])
async def get_jobs(md5_hashes: List[str]):
    """
    Returns the prediction status for a list of jobs, specified by md5 hash.

    :param md5_hashes: List of image md5 hashes
    :return: Array of image prediction results.
    """
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


@model_router.post("/search")
def search_images(
        current_user: User = Depends(current_user_investigator),
        page_id: int = -1,
        search_string: str = '',
        search_filter: dependency.SearchFilter = None,
):
    """
    Returns a list of image hashes of images submitted by a user. Pagination of image hashes as
    well as searching is provided by this method.

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
    """
    Returns a list of all image hashes that match a search criteria. This is used for downloading on the client-side
    bulk image information.

    :param current_user: Currently logged in user
    :param search_string: String to search metadata field of UniversalMLImage object
    :param search_filter: Model JSON search for matching fields
    :return: List of image hashes associated with user
    """
    if search_string == '' and not search_filter:
        return {
            'status': 'failure',
            'detail': 'You must specify a search string or search filter'
        }

    if not search_filter:
        filter_to_use = {}
    else:
        filter_to_use = search_filter.search_filter

    db_result = get_images_from_user_db(
        current_user.username,
        search_filter=filter_to_use,
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
    Validates an API key contained in the header. This also ensures that the API key is authorized to
    make prediction requests.

    :param api_key_header: Request header containing {'API_KEY': 'someKeyValue'}
    :return: APIKeyData object on success, else will raise HTTP CredentialException
    """

    api_key_data = get_api_key_by_key_db(api_key_header)
    if not api_key_data or not api_key_data.enabled or api_key_data.type != dependency.ExternalServices.predict_microservice.name:
        raise dependency.CredentialException
    return api_key_data


@model_router.post("/register", dependencies=[Depends(get_api_key)])
def register_model(model: MicroserviceConnection):
    """
    Register a single model to the server by adding the model's name and socket
    to available model settings. Also kick start a separate thread to keep track
    of the model service status. Models that are registered must use a valid API key.

    :param model: MicroserviceConnection object with the model name and model socket.
    :return: {'status': 'success'} if registration successful else {'status': 'failure'}
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
    if model.name in settings.available_models:
        return {
            "status": "success",
            'model': model.name,
            'detail': 'Model has already been registered.'
        }

    # Ensure that we can connect back to model before adding it
    try:
        r = requests.get(model.socket + '/status')
        r.raise_for_status()
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
        return {
            "status": "failure",
            'model': model.name,
            'detail': 'Unable to establish successful connection to model.'
        }

    # Register model to server and create thread to ensure model is responsive
    settings.available_models[model.name] = model.socket
    pool.submit(ping_model, model.name)

    logger.debug("Model " + model.name + " successfully registered to server.")

    return {
        "status": "success",
        'model': model.name,
        'detail': 'Model has been successfully registered to server.'
    }


def get_model_prediction(socket: str, image_hash: str, model_name: str, image_file: UploadFile = File(...)):
    """
    Helper method that a worker will use to generate a prediction for a given model. This will be run in a task
    by any redis queue worker that is registered.

    :param host: Model server host. If running locally then "localhost" or "host.docker.internal"
    :param socket: Socket the model is running on
    :param filename: Name of the image file that a prediction is being generated on
    :param image_hash: md5 hash of the image file that is having a prediction done
    :param model_name: Name of the model that is being used.
    :return: Model prediction results
    """
    # Receive Prediction from Model

    args = {'file': image_file}
    try:
        request = requests.post(socket + '/predict', files=args)
        request.raise_for_status()  # Ensure model connection is successful
        if request.json()['status'] == 'success':
            model_result = request.json()['result']['result']
            model_classes = request.json()['result']['classes']
            print("\n\n\n", model_result, "\n\n\n")
        else:
            print('Failure on predicting image ' + image_hash + ' on model ' + model_name)
            return
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
        print('Fatal error when predicting image ' + image_hash + ' on model ' + model_name)
        return

    # Store result of model prediction into database
    if dependency.image_collection.find_one({"hash_md5": image_hash}):
        image_object = get_image_by_md5_hash_db(image_hash)
        add_model_to_image_db(image_object, model_name, model_result)
        add_model_db(model_name, model_classes)
    try:
        os.remove('/app/images/'+filename)
    except OSError:
        pass
    return model_result


def ping_model(model_name):
    """
    Periodically ping a model's service to make sure that it is active. If it's not, remove the model from the
    available_models BaseSetting in dependency.py

    :param model_name: Name of model to ping. This is the name the model registered to the server with.
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
