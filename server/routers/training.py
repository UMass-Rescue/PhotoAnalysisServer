import os
import shutil
import time

import requests
from fastapi import Depends, APIRouter, UploadFile, File
from starlette import status
from starlette.responses import JSONResponse, FileResponse

import dependency
from db_connection import get_api_key_by_key_db, update_training_result_db, get_training_result_by_training_id, \
    add_training_result_db, get_training_statistics_db, get_bulk_training_results_reverse_order_db
from dependency import logger, MicroserviceConnection, settings, pool, APIKeyData
from routers.auth import current_user_researcher, current_user_admin

training_router = APIRouter()


@training_router.get("/list", dependencies=[Depends(current_user_researcher)])
async def get_available_training_datasets():
    """
    Returns list of available datasets to the client. This list can be used when calling get_prediction,
    with the request
    """
    return {"datasets": [*settings.available_datasets]}


@training_router.get("/detail")
async def get_training_stats(u: dependency.User = Depends(current_user_researcher)):
    """
    Returns basic statistics on training results.
    """

    if dependency.Roles.admin.name in u.roles:
        pending, finished = get_training_statistics_db()
    else:
        pending, finished = get_training_statistics_db(u.username)

    return {
        'status': 'success',
        'pending': pending,
        'finished': finished
    }


@training_router.post('/train')
async def send_training_request(training_data: dependency.TrainingRequestHttpBody, user=Depends(current_user_researcher)):
    """
    Creates a new training request and sends it to the correct dataset to be trained. Returns a unique
    training id which can be used to track the training status.
    """

    if training_data.dataset not in settings.available_datasets:
        return {
            'status': 'failure',
            'detail': 'Invalid dataset specified.',
            'dataset': training_data.dataset
        }

    try:
        r = requests.post(
            'http://host.docker.internal:' + str(settings.available_datasets[training_data.dataset]) + '/train',
            json={
                'model_structure': training_data.model_structure,
                'loss_function': training_data.loss_function,
                'optimizer': training_data.optimizer,
                'n_epochs': training_data.n_epochs,
                'save': training_data.save_training_results
            }
        )
        r.raise_for_status()

        training_id = r.json()['id']

        training_result = dependency.TrainingResult(**{
            'dataset': training_data.dataset,
            'training_id': training_id,
            'username': user.username,
            'complete': False,
            'model': training_data.dict(),
            'save': training_data.save_training_results
        })

        add_training_result_db(training_result)

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
        return {
            'status': 'failure',
            'detail': 'Unable to establish connection with dataset server.'
        }

    return {
        'status': 'success',
        'detail': 'Training job created successfully. Check back later with the training id for results.',
        'training_id': training_id
    }


@training_router.get("/result")
async def get_training_result(training_id: str = '', user=Depends(current_user_researcher)):
    """
    Returns training result for a given training ID.
    """

    # Ensure fields are present in HTTP request
    if len(training_id) == 0:
        return {
            'status': 'failure',
            'detail': 'Please provide training_id to check status'
        }

    # Lookup training result
    training_result = get_training_result_by_training_id(training_id)

    # If it doesn't exist or user can't access it
    if not training_result or (
            training_result.username != user.username and dependency.Roles.admin.name not in user.roles):
        return {
            'status': 'failure',
            'detail': 'Unable to find training result with ID.',
            'training_id': training_id
        }

    # Check if status is pending
    if not training_result.complete:
        return {
            'status': 'success',
            'detail': 'Training job is currently processing. Please check back later.',
            'dataset': training_result.dataset,
            'training_id': training_id
        }

    return {
        'status': 'success',
        **training_result.dict()
    }


@training_router.get("/results")
async def get_bulk_training_results(limit: int = -1, u: dependency.User = Depends(current_user_researcher)):
    """
    Returns basic statistics on training results.
    """

    if dependency.Roles.admin.name in u.roles:
        results = get_bulk_training_results_reverse_order_db(limit)
    else:
        results = get_bulk_training_results_reverse_order_db(limit, u.username)

    return {
        'status': 'success',
        'jobs': results
    }


@training_router.get('/model', dependencies=[Depends(current_user_admin)])
async def download_trained_model_data(training_id: str):

    result = get_training_result_by_training_id(training_id)
    if not result:
        return {
            'status': 'failure',
            'detail': 'Unable to find training result with specified ID.',
            'training_id': training_id
        }

    if not result.save:
        return {
            'status': 'failure',
            'detail': 'No model files available. User did not request results saved in training request.',
            'training_id': training_id
        }

    if not result.complete:
        return {
            'status': 'success',
            'detail': 'Training job is currently processing. Please check back later to download files.',
            'training_id': training_id
        }

    if not os.path.exists('/app/training_results/'+training_id+'.zip'):
        return {
            'status': 'failure',
            'detail': 'Unable to locate trained model files.',
            'training_id': training_id
        }

    return FileResponse(
        '/app/training_results/'+training_id+'.zip',
        media_type='application/octet-stream',
        filename='Trained Model ' + training_id + '.zip')

# ----------------------------------------------------------------
#                   External Connection Methods
# ----------------------------------------------------------------


def get_api_key(api_key_header: str = Depends(dependency.api_key_header_auth)):
    """
    Validates an API contained in the header. For some reason, this method will ONLY function
    when in the same file as the Depends(...) check. Therefore, this is not in auth.py
    """

    api_key_data = get_api_key_by_key_db(api_key_header)
    if not api_key_data or not api_key_data.enabled or api_key_data.type != dependency.ExternalServices.dataset_microservice.name:
        raise dependency.CredentialException
    return api_key_data


@training_router.post('/result', dependencies=[Depends(get_api_key)])
async def save_training_result(r: dependency.TrainingResultHttpBody):


    tr = get_training_result_by_training_id(r.training_id)
    tr.training_accuracy = r.results['training_accuracy']
    tr.validation_accuracy = r.results['validation_accuracy']
    tr.training_loss = r.results['training_loss']
    tr.validation_loss = r.results['validation_loss']
    tr.complete = True
    update_training_result_db(tr)
    return {
        'status': 'success',
        'detail': 'Training data successfully updated.'
    }


@training_router.post('/model', dependencies=[Depends(get_api_key)])
async def save_model_to_disk(training_id: str = '', model: UploadFile = File(...)):
    """
    Saves model to disk.
    """

    logger.debug('Training ID: ' + training_id)

    if not get_training_result_by_training_id(training_id):
        return {
            'status': 'failure',
            'detail': 'Unable to find training result with specified ID',
            'training_id': training_id
        }

    upload_folder = open(os.path.join('/app/training_results', model.filename), 'wb+')
    shutil.copyfileobj(model.file, upload_folder)
    upload_folder.close()
    return {
        'status': 'success',
        'detail': 'Training results uploaded successfully',
        'training_id': training_id
    }


@training_router.post("/register")
def register_dataset(dataset: MicroserviceConnection
                     , api_key: APIKeyData = Depends(get_api_key)
                     ):
    """
    Register a single dataset to the server by adding the name and port
    to available dataset settings. Also kick start a separate thread to keep track
    of the dataset service status
    """

    # Do not accept calls if server is in process of shutting down
    if dependency.shutdown:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                'status': 'failure',
                'detail': 'Server is shutting down. Unable to complete new dataset registration.'
            }
        )

    # Do not add duplicates of running datasets to server
    if dataset.name in settings.available_datasets:
        return {
            "status": "success",
            'dataset': dataset.name,
            'detail': 'Dataset has already been registered.'
        }

    # Ensure that we can connect back to dataset before adding it
    try:
        r = requests.get('http://host.docker.internal:' + str(dataset.port) + '/status')
        r.raise_for_status()
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
        return {
            "status": "failure",
            'dataset': dataset.name,
            'detail': 'Unable to establish successful connection to dataset.'
        }

    # Register dataset to server and create thread to ensure dataset is responsive
    settings.available_datasets[dataset.name] = dataset.port
    pool.submit(ping_dataset, dataset.name)

    logger.debug("Dataset " + dataset.name + " successfully registered to server.")

    return {
        "status": "success",
        'dataset': dataset.name,
        'detail': 'Dataset has been successfully registered to server.'
    }


def ping_dataset(dataset_name):
    """
    Periodically ping the dataset's service to make sure that
    it is active. If it's not, remove the dataset from the available_datasets setting
    """

    dataset_is_alive = True

    def kill_dataset():
        settings.available_datasets.pop(dataset_name)
        nonlocal dataset_is_alive
        dataset_is_alive = False
        logger.debug("Dataset " + dataset_name + " is not responsive. Removing from available services...")

    while dataset_is_alive and not dependency.shutdown:
        try:
            r = requests.get(
                'http://host.docker.internal:' + str(settings.available_datasets[dataset_name]) + '/status')
            r.raise_for_status()
            for increment in range(dependency.WAIT_TIME):
                if not dependency.shutdown:  # Check between increments to stop hanging on shutdown
                    time.sleep(1)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
            kill_dataset()
            return

    if dependency.shutdown:
        logger.debug("Dataset [" + dataset_name + "] Healthcheck Thread Terminated.")
