from pymongo import MongoClient

from auth import User

client = MongoClient('database', 27017)
database = client['image_result_db']
image_collection = database['images']  # Create collection for images in database
user_collection = database['users']  # Create collection for images in database

# ---------------------------
# User Database Interactions
# ---------------------------

# def add_user_db(user: User):
#     """
#     Add a new user to the database.
#     """
#     if not user_collection.find_one({"id": user.id}):
#         image_collection.insert_one({**user})


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
