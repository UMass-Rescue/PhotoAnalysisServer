import requests
from pymongo import MongoClient

client = MongoClient('database', 27017)
database = client['image_result_db']
image_collection = database['images']  # Create collection for images in database


def get_model_prediction(host, port, filename, image_hash, model_name):
    # Receive Prediction from Model

    args = {'filename': filename}
    result = requests.post('http://' + host + ':' + str(port) + '/predict', params=args).json()['result']

    # Store result of model prediction into database
    if image_collection.find_one({"_id": image_hash}):
        image_collection.update_one({'_id': image_hash}, {'$set': {'models.' + model_name: result}})

    return result
