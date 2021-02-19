import pytest

from db_connection import get_user_by_name_db
from main import app
from routers.auth import create_testing_account
from routers.auth import get_current_active_user, current_user_investigator, current_user_researcher, \
    current_user_admin

@pytest.fixture(scope="session", autouse=True)
def execute_before_any_test():
    create_testing_account()  # Ensure testing account is created

    # Override all permissions to return the testing user object. This allows us to bypass the OAuth2 authentication
    app.dependency_overrides[get_current_active_user] = override_logged_in_user
    app.dependency_overrides[current_user_investigator] = override_logged_in_user
    app.dependency_overrides[current_user_researcher] = override_logged_in_user
    app.dependency_overrides[current_user_admin] = override_logged_in_user

def override_logged_in_user():
    return get_user_by_name_db('testing')