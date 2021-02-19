from fastapi.testclient import TestClient

from dependency import CredentialException
from main import app
from routers.auth import get_current_active_user
from test.conftest import override_logged_in_user

client = TestClient(app)



def test_status():
    response = client.get("/auth/status")
    assert response.status_code == 200
    assert 'status' in response.json()


def test_profile():
    response = client.get("/auth/profile")
    assert response.status_code == 200
    assert 'disabled' in response.json() and not response.json()['disabled']


def test_get_no_api_keys():
    response = client.get("/auth/key")
    assert response.status_code == 200
    assert len(response.json()['keys']) == 0


def test_create_delete_api_keys():
    # Create new key
    create_key_response = client.post("/auth/key?key_owner_username=testing&service=predict_microservice&detail=TestingKey")
    assert create_key_response.status_code == 200
    assert 'status' in create_key_response.json() and create_key_response.json()['status'] == 'success'

    api_key = create_key_response.json()['key']

    # Check key is valid
    check_keys_response = client.get("/auth/key")
    assert check_keys_response.status_code == 200
    assert len(check_keys_response.json()['keys']) == 1

    # Delete created key
    delete_key_response = client.delete('/auth/key?key='+api_key)
    assert delete_key_response.status_code == 200

    # Ensure no keys remain
    check_keys_response = client.get("/auth/key")
    assert check_keys_response.status_code == 200
    assert len(check_keys_response.json()['keys']) == 0


def test_create_invalid_api_key():

    # Request invalid username
    response_bad_username = client.post('/auth/key?' +
        'key_owner_username=invalidUSERNAMEhere1234567890' +
        '&service=predict_microservice' +
        '&detail=TestingKey'
    )
    assert response_bad_username.status_code == 200
    assert 'status' in response_bad_username.json() and response_bad_username.json()['status'] == 'failure'

    # Request bad microservice
    response_bad_service = client.post('/auth/key?' +
        'key_owner_username=testing' +
        '&service=microservice_that_does_not_exist' +
        '&detail=TestingKey'
    )
    assert response_bad_service.status_code == 200
    assert 'status' in response_bad_service.json() and response_bad_service.json()['status'] == 'failure'

    # Ensure no keys created
    check_keys_response = client.get("/auth/key")
    assert check_keys_response.status_code == 200
    assert len(check_keys_response.json()['keys']) == 0


def test_delete_invalid_api_key():
    delete_key_response = client.delete('/auth/key?key=abc123IDONOTEXIST')
    assert delete_key_response.status_code == 200
    assert 'status' in delete_key_response.json() and delete_key_response.json()['status'] == 'failure'



def test_endpoint_no_permissions():

    def override_logged_out_user():  # Simulate access to endpoint for user with no permissions
        raise CredentialException()

    app.dependency_overrides[get_current_active_user] = override_logged_out_user
    response = client.get("/auth/status")
    assert response.status_code == 401
    app.dependency_overrides[get_current_active_user] = override_logged_in_user


def test_permission_change():
    add_role_response = client.post('/auth/add_role?username=testing&role=investigator')
    assert add_role_response.status_code == 200
    assert 'status' in add_role_response.json() and add_role_response.json()['status'] == 'success'

    check_roles_response = client.get("/auth/profile")
    assert check_roles_response.status_code == 200
    assert 'investigator' in check_roles_response.json()['roles']

    del_role_response = client.post('/auth/remove_role?username=testing&role=investigator')
    assert add_role_response.status_code == 200
    assert 'status' in del_role_response.json() and del_role_response.json()['status'] == 'success'

    check_roles_response = client.get("/auth/profile")
    assert check_roles_response.status_code == 200
    assert 'investigator' not in check_roles_response.json()['roles']


def test_permission_add_bad_role():
    initial_roles_response = client.get("/auth/profile")
    assert initial_roles_response.status_code == 200

    add_role_response = client.post('/auth/add_role?username=testing&role=thisROLEdoesNOTexist')
    assert add_role_response.status_code == 200
    assert 'status' in add_role_response.json() and add_role_response.json()['status'] == 'failure'

    check_roles_response = client.get("/auth/profile")
    assert check_roles_response.status_code == 200
    assert check_roles_response.json()['roles'] == check_roles_response.json()['roles']


def test_permission_del_bad_role():
    initial_roles_response = client.get("/auth/profile")
    assert initial_roles_response.status_code == 200

    del_role_response = client.post('/auth/remove_role?username=testing&role=thisROLEdoesNOTexist')
    assert del_role_response.status_code == 200
    assert 'status' in del_role_response.json() and del_role_response.json()['status'] == 'failure'

    check_roles_response = client.get("/auth/profile")
    assert check_roles_response.status_code == 200
    assert check_roles_response.json()['roles'] == check_roles_response.json()['roles']