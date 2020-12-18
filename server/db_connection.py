from typing import Union

from dependency import User, user_collection, image_collection, PAGINATION_PAGE_SIZE, UniversalMLImage, Roles
import math


# ---------------------------
# User Database Interactions
# ---------------------------


def add_user_db(user: User) -> dict:
    """
    Add a new user to the database.
    """

    # User types define permissions.
    if user.roles is None:
        roles = []

    if not user_collection.find_one({"username": user.username}):
        user_collection.insert_one(user.dict())
        return {'status': 'success', 'detail': 'account with username [' + str(user.username) + '] created.'}
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


def add_image_db(image: UniversalMLImage):
    """
    Adds a new image to the database based on the UniversalMLImage model.
    """

    if not image_collection.find_one({"hash_md5": image.hash_md5}):
        image_collection.insert_one(image.dict())


def add_user_to_image(image: UniversalMLImage, username: str):
    """
    Adds a user account to an image. This is used to track what users upload images
    :param image: UniversalMLImage to update
    :param username: Username of user who is accessing image
    :return: None
    """
    if image_collection.find_one({"hash_md5": image.hash_md5}):
        existing_users = image_collection.find_one({"hash_md5": image.hash_md5})['users']
        if username not in existing_users:  # Only update if not in list already
            image_collection.update_one(
                {"hash_md5": image.hash_md5},
                {'$set': {'users': [existing_users, username]}}
            )


def get_images_from_user_db(username: str, page: int = -1):
    """
    Returns a list of image hashes associated with the username. If a page number is provided, will return
    PAGINATION_PAGE_SIZE
    :param page: Page to return of results. Will return all if page is -1
    :param username: Username of user to get images for
    :return: Array of image hashes, total pages
    """
    user = get_user_by_name_db(username)
    if not user:  # If user does not exist, return empty
        return [], 0

    if page < 0:
        if Roles.admin.name in user.roles:
            result = list(image_collection.find({}, {"hash_md5"}))
        else:
            result = list(image_collection.find({"users": username}, {"hash_md5"}))
    else:
        # We use this for actual db queries. Page 1 = index 0
        page_index = page - 1
        if Roles.admin.name in user.roles:
            result = list(image_collection.find({}, {"hash_md5"}).skip(PAGINATION_PAGE_SIZE * page_index).limit(PAGINATION_PAGE_SIZE))
        else:
            result = list(image_collection.find({"users": username}, {"hash_md5"}).skip(PAGINATION_PAGE_SIZE * page_index).limit(
                PAGINATION_PAGE_SIZE))

    # Finally convert the dict of results to a flat list
    result = [image_map['hash_md5'] for image_map in result]
    if Roles.admin.name in user.roles:
        num_images = len(list(image_collection.find({}, {"hash_md5"})))
    else:
        num_images = len(list(image_collection.find({"users": username}, {"hash_md5"})))
    return {
        "hashes": result,
        "num_pages": math.ceil(num_images / PAGINATION_PAGE_SIZE),
        "num_images": num_images
    }


def get_models_from_image_db(image: UniversalMLImage, model_name=""):
    projection = {
        "_id": 0,
        "models": 1
    }

    if not image_collection.find_one({"hash_md5": image.hash_md5}):
        return {}

    if model_name != "":
        results = image_collection.find_one({"hash_md5": image.hash_md5}, projection)
        return {model_name: results['models'][model_name]}
    else:
        return image_collection.find_one({"hash_md5": image.hash_md5}, projection)['models']


def get_image_by_md5_hash_db(image_hash) -> Union[UniversalMLImage, None]:
    if not image_collection.find_one({"hash_md5": image_hash}):
        return None

    result = image_collection.find_one({"hash_md5": image_hash})
    result.pop('_id')
    return UniversalMLImage(**result)
