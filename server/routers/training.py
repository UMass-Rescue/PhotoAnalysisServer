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
    Returns list of available dataset names to the client. The names of the datasets returned here can be used
    when making training requests for a specific dataset.

    :return: {'datasets': List[str]} with names of all datasets available for training.
    """
    return {"datasets": [*settings.available_datasets]}


@training_router.get("/detail")
async def get_training_stats(u: dependency.User = Depends(current_user_researcher)):
    """
    Returns statistics on the number of currently training jobs and finished jobs. If the user is an administrator,
    they will see the status of all training jobs and completed jobs on the server, otherwise the user will only see
    the number of training and completed jobs that they have submitted.

    :param u: Current User. This field is automatically generated from the authentication header parsing.
    :return: {'status': 'success'} with statistics if successful, else {'status': 'failure'}
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
    Creates a new training request and sends it to the correct dataset to be trained. The unique training id that
    is returned from this method will be used to query the status of the training job and track it throughout
    the system.

    :param training_data: TrainingRequestHttpBody object to be sent to the corresponding dataset
    :param user: Current User. This field is automatically generated from the authentication header parsing.
    :return: {'status': 'success'} with 'training_id' if successful, else {'status': 'failure'}
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
    Provides training results for a given training ID. The 'detail' field in JSON will provide specific
    information on the job and its current processing status. An admin may query any job and receive results, but
    other users will only be able to query job IDs that they have submitted.

    :param training_id: ID that will have records pulled for.
    :param user: Current User. This field is automatically generated from the authentication header parsing.
    :return: {'status': 'success'} with training statistics if successful, else {'status': 'failure'}
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
    Returns training results for a given user, in order of date (descending). If the user making the request is an
    administrator, this method will return all training results regardless of user. Otherwise, this will only return
    the last records submitted by a given person.

    :param limit: Number of jobs to return. If -1, will return all training results.
    :param u: Current User. This field is automatically generated from the authentication header parsing.
    :return: {'status': 'success'} and job list on success, else HTTP error.
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
    """
    Allows user to download a .zip file containing a SavedModel object. This will have the trained weights from
    the remote training job, and the results may be loaded back into Tensorflow2. Only admins are able to download
    training results, regardless of who submits the training jobs initially.

    :param training_id: Training ID of job to download
    :return: application/octet-stream with .zip file containing SavedModel object
    """
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

    :param api_key_header: Header of HTTP request containing {'API_KEY': 'keyGoesHere'}
    :return: APIKeyData object on success, else will raise CredentialException
    """
    api_key_data = get_api_key_by_key_db(api_key_header)
    if not api_key_data or not api_key_data.enabled or api_key_data.type != dependency.ExternalServices.dataset_microservice.name:
        raise dependency.CredentialException
    return api_key_data


@training_router.post('/result', dependencies=[Depends(get_api_key)])
async def save_training_result(r: dependency.TrainingResultHttpBody):
    """
    Saves the model training statistics to the database. This method is called only by registered dataset
    microservices.

    :param r:  Training Result with updated fields sent by dataset microservice
    :return: {'status': 'success'} if successful update, else http error.
    """
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
    Receives a .zip file containing a tensorflow2 SavedModel object sent by a dataset microservice.
    Then, will store the .zip file in trained model docker volume, with the naming format of
    <training_id>.zip

    :param training_id: Training ID the model is associated with
    :param model: .zip file containing SavedModel object
    :return: {'status': 'success'} if saving is successful, else {'status': 'failure'}
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


@training_router.post("/register", dependencies=[Depends(get_api_key)])
def register_dataset(dataset: MicroserviceConnection):
    """
    Register a single dataset to the server by adding the name and port
    to available dataset settings. Also kick start a separate thread to keep track
    of the dataset service status. A valid dataset API key must be in the request
    header for this method to run.

    :param dataset: MicroserviceConnection object with name and port of dataset
    :return: {'status': 'success'} if saving is successful, else {'status': 'failure'}
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
    Periodically ping a dataset's service to make sure that it is active and able to receive requests.
    If it's not, remove the dataset from the available_datasets map. This is a helper method that is
    not directly exposed via HTTP.

    :param dataset_name: Name of a registered dataset as a string
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
