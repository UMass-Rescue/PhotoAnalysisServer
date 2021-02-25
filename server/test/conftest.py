import pytest

from routers import model, training

from dependency import api_key_collection
from db_connection import get_user_by_name_db, get_api_keys_by_user_db
from main import app
from routers.auth import create_testing_account, create_testing_keys
from routers.auth import (
    get_current_active_user,
    current_user_investigator,
    current_user_researcher,
    current_user_admin,
)


@pytest.fixture(scope="session", autouse=True)
def test_configuration():
    create_testing_account()  # Ensure testing account is created
    create_testing_keys()  # Ensure API keys are created

    # Override all permissions to return the testing user object. This allows us to bypass the OAuth2 authentication
    app.dependency_overrides[get_current_active_user] = override_logged_in_user
    app.dependency_overrides[current_user_investigator] = override_logged_in_user
    app.dependency_overrides[current_user_researcher] = override_logged_in_user
    app.dependency_overrides[current_user_admin] = override_logged_in_user
    app.dependency_overrides[model.get_api_key] = override_api_key_prediction
    app.dependency_overrides[training.get_api_key] = override_api_key_training

    yield

    api_key_collection.delete_many({'user': 'testing'})  # Delete all API keys created during testing



def override_logged_in_user():
    return get_user_by_name_db("testing")

def override_api_key_prediction():
    return get_api_keys_by_user_db(get_user_by_name_db('api_key_testing'))[0]

def override_api_key_training():
    return get_api_keys_by_user_db(get_user_by_name_db('api_key_testing'))[1]
