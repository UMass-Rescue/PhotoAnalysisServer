from typing import Union


from dependency import User, user_collection, image_collection


# ---------------------------
# User Database Interactions
# ---------------------------


def add_user_db(username, hashed_password, email, full_name, roles=None) -> dict:
    """
    Add a new user to the database.
    """

    # User types define permissions.
    if roles is None:
        roles = []

    if not user_collection.find_one({"_id": 0}):
        next_id = 0
    else:
        next_id = user_collection.find_one(sort=[("_id", -1)])['_id'] + 1

    if not user_collection.find_one({"username": username}):
        user_collection.insert_one({
            '_id': next_id,
            'username': username,
            'password': hashed_password,
            'email': email,
            'full_name': full_name,
            'roles': roles,
            'disabled': False,
        })
        return {'status': 'success', 'detail': 'account with username [' + str(username) + '] created.'}
    else:
        return {'status': 'failure', 'detail': 'Account  with this username already exists'}


def get_user_by_name_db(username: str) -> Union[User, None]:
    """
    Finds a user in the database by a given username
    :param username: username of user
    :return: User with successful record or None
    """
    if not user_collection.find_one({"username": username}):
        return None

    database_result = user_collection.find_one({"username": username})
    user_object = User(**database_result)
    return user_object


def set_user_roles_db(username: str, updated_roles: list) -> bool:
    """
    Sets the roles for a given user
    :param username: Username of user that will have roles modified
    :param updated_roles: Array of roles that user will now have
    :return: Success: True or False
    """
    if not user_collection.find_one({"username": username}):
        return False

    user_collection.update_one({'username': username}, {'$set': {'roles': updated_roles}})
    return True

# ---------------------------
# Image Database Interactions
# ---------------------------


def add_image_db(image_hash: str, file_name: str):
    """
    Add a new image to the database.
    """

    if not image_collection.find_one({"_id": image_hash}):
        image_collection.insert_one({
            "_id": image_hash,
            "filename": file_name,
            "models": {}
        })


def get_models_from_image_db(image_hash, model_name=""):
    projection = {
        "_id": 0,
        "models": 1
    }

    if not image_collection.find_one({"_id": image_hash}):
        return {}

    if model_name != "":
        results = image_collection.find_one({"_id": image_hash}, projection)
        return {model_name: results['models'][model_name]}
    else:
        return image_collection.find_one({"_id": image_hash}, projection)['models']


def get_image_filename_from_hash_db(image_hash):
    if not image_collection.find_one({"_id": image_hash}):
        return {}

    return image_collection.find_one({"_id": image_hash})['filename']
