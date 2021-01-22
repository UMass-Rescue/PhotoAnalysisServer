from typing import Union, List

from dependency import User, user_collection, image_collection, PAGINATION_PAGE_SIZE, UniversalMLImage, Roles, \
    APIKeyData, \
    api_key_collection, model_collection, TrainingResult, training_collection, logger
import math
import json


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
# API Key Database Interactions
# ---------------------------

def add_api_key_db(key: APIKeyData) -> dict:
    """
    Add a new API key to the database.
    """

    if not api_key_collection.find_one({"key": key.key}):
        api_key_collection.insert_one(key.dict())
        return {'status': 'success', 'detail': 'API key successfully added.'}
    else:
        return {'status': 'failure', 'detail': 'API key with desired key already exists.'}


def get_api_key_by_key_db(key: str) -> Union[APIKeyData, None]:
    """
    Gets an API key object from the key string. Will return NoneType if no API key
    for a given key string exists.
    """
    if not api_key_collection.find_one({"key": key}):
        return None

    database_result = api_key_collection.find_one({"key": key})
    api_key_object = APIKeyData(**database_result)
    return api_key_object


def get_api_keys_by_user_db(user: User) -> List[APIKeyData]:
    """
    Gets all API keys that are active and are tied to a given user.
    """
    if not api_key_collection.find_one({"user": user.username}):
        return []

    database_results = list(api_key_collection.find({"user": user.username, 'enabled': True}))
    user_keys = [APIKeyData(**res) for res in database_results]
    return user_keys


def set_api_key_enabled_db(key: APIKeyData, enabled: bool) -> bool:
    """
    Enables or disables a given API key
    :param key: API key object that is being modified in the DB
    :param enabled: Key will be enabled (true) or disabled (false)
    :return: Success: True or False
    """
    if not api_key_collection.find_one({"key": key.key}):
        return False

    api_key_collection.update_one({'key': key.key}, {'$set': {'enabled': enabled}})
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
        existing_users = list(image_collection.find_one({"hash_md5": image.hash_md5})['users'])
        if username not in existing_users:  # Only update if not in list already
            existing_users.append(username)
            image_collection.update_one(
                {"hash_md5": image.hash_md5},
                {'$set': {'users': existing_users}}
            )


def add_filename_to_image(image: UniversalMLImage, filename: str):
    """
    Adds a filename to an image. This is used to track all names a file goes by
    :param image: UniversalMLImage to update
    :param filename: file name with extension
    :return: None
    """
    if image_collection.find_one({"hash_md5": image.hash_md5}):
        current_names = list(image_collection.find_one({"hash_md5": image.hash_md5})['file_names'])
        if filename not in current_names:  # Only update if not in list already
            current_names.append(filename)
            image_collection.update_one(
                {"hash_md5": image.hash_md5},
                {'$set': {'file_names': current_names}}
            )


def add_model_to_image_db(image: UniversalMLImage, model_name, result):
    new_metadata = [list(image.dict().values()), model_name, result]
    image_collection.update_one({'hash_md5': image.hash_md5}, {'$set': {
        'models.' + model_name: result,
        'metadata': json.dumps(new_metadata)
    }})


def get_images_from_user_db(
        username: str,
        page: int = -1,
        search_filter: dict = None,
        search_string: str = '',
        paginate: bool = True
):
    """
    Returns a list of image hashes associated with the username. If a page number is provided, will return
    PAGINATION_PAGE_SIZE
    :param username: Username of user to get images for
    :param page: Page to return of results. Will return all if page is -1
    :param search_filter Optional filter to narrow down query
    :param search_string String that will be matched against image metadata
    :param paginate Return all results or only page
    :return: Array of image hashes, total pages
    """

    user = get_user_by_name_db(username)
    if not user:  # If user does not exist, return empty
        return [], 0

    # If there is a filter, start with the correct dataset that has been filtered already
    # Generate the result of the query in this step
    if search_filter or search_string:
        # List comprehension to take the inputted filter and make it into a pymongo query-compatible expression
        search_params = []
        if search_filter:  # Append search filter
            flat_model_filter = (
                [{'models.' + model + '.' + str(model_class): {'$gt': 0}} for model in search_filter for model_class in
                 search_filter[model]])
            search_params.append({'$or': flat_model_filter})
        if search_string:  # Append search string
            search_params.append({"metadata": {'$regex': search_string, '$options': 'i'}})
        if Roles.admin.name not in user.roles:  # Add username to limit results if not admin
            search_params.append({'users': username})

        result = image_collection.find({'$and': search_params}, {"hash_md5"})
    else:
        if Roles.admin.name in user.roles:
            result = image_collection.find({}, {"hash_md5"})
        else:
            result = image_collection.find({'users': username}, {"hash_md5"})

    # If we are getting a specific page of images, then generate the list of hashes
    final_hash_list = []
    if page > 0 and paginate:
        # We use this for actual db queries. Page 1 = index 0
        page_index = page - 1
        final_hash_list = result.skip(PAGINATION_PAGE_SIZE * page_index).limit(PAGINATION_PAGE_SIZE)

        # After query, convert the result to a list
        final_hash_list = [image_map['hash_md5'] for image_map in list(final_hash_list)]
    elif not paginate:  # Return all results
        final_hash_list = [image_map['hash_md5'] for image_map in list(result)]

    num_images = result.count()
    return_value = {
        "hashes": final_hash_list,
        "num_images": num_images
    }
    if paginate:
        return_value["num_pages"] = math.ceil(num_images / PAGINATION_PAGE_SIZE)

    return return_value


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


# ---------------------------
# Model Database Interactions
# ---------------------------


def add_model_db(model_name, model_fields):
    if not model_collection.find_one({'model_name': model_name}):
        model_collection.insert_one({
            'model_name': model_name,
            'model_fields': model_fields
        })


def get_models_db():
    all_models = list(model_collection.find())
    model_list = {model['model_name']: model['model_fields'] for model in all_models}
    return model_list


# ------------------------------
# Training Database Interactions
# ------------------------------

def add_training_result_db(tr: TrainingResult):
    if not training_collection.find_one({'training_id': tr.training_id}):
        training_collection.insert_one(tr.dict())


def update_training_result_db(tr: TrainingResult):
    if not training_collection.find_one({'training_id': tr.training_id}):
        add_training_result_db(tr)
    else:
        training_collection.replace_one({'training_id': tr.training_id}, tr.dict())


def get_training_result_by_training_id(training_id: str):
    if not training_collection.find_one({'training_id': training_id}):
        return None

    res = training_collection.find_one({'training_id': training_id})

    return TrainingResult(**res)


def get_bulk_training_results_reverse_order_db(limit: int = -1, username: str = ''):
    """
    Gets the last N results for submitted training requests optionally by a user
    """

    query = {'username': username} if len(username) > 0 else {}
    if limit > 0:
        res = training_collection.find(query, {'_id': False}).sort([('$natural', -1)]).limit(limit)
    else:
        res = training_collection.find(query, {'_id': False}).sort([('$natural', -1)])

    return list(res)


def get_training_statistics_db(username: str = None):
    if username is not None:
        u = get_user_by_name_db(username)
        finished = training_collection.find({'username': username, 'complete': True})
        pending = training_collection.find({'username': username, 'complete': False})
    else:
        finished = training_collection.find({'complete': True})
        pending = training_collection.find({'complete': False})

    return pending.count(), finished.count()
