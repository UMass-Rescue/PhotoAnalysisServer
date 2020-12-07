from pymongo import MongoClient

client = MongoClient('database', 27017)
database = client['server_database']
image_collection = database['images']  # Create collection for images in database
user_collection = database['users']  # Create collection for users in database

# ---------------------------
# User Database Interactions
# ---------------------------


def add_user_db(username, hashed_password, roles=None):
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
            'roles': roles,
            'disabled': False,
        })
        return {'status': 'success', 'detail': 'account with username [' + str(username) + '] created.'}
    else:
        return {'status': 'failure', 'detail': 'Account  with this username already exists'}


def get_user_by_name_db(username: str):
    """
    Finds a user in the database by a given username
    :param username: username of user
    :return: UserInDB with successful record or None
    """
    if not user_collection.find_one({"username": username}):
        return None

    return user_collection.find_one({"username": username})


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
