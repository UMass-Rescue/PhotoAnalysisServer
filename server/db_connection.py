from pymongo import MongoClient

client = MongoClient('database', 27017)
database = client['image_result_db']
image_collection = database['images']  # Create collection for images in database


def create_db_image(image_hash: str):
    """
    Add a new image to the database.
    """

    if not image_collection.find_one({"_id": image_hash}):
        image_collection.insert_one({
            "_id": image_hash,
            "models": {}
        })
        print("Added!")
    else:
        print("Exists!")


def get_models_from_db_image(image_hash, model_name=""):
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

