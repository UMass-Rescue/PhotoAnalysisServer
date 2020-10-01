from typing import List

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import os
import hashlib
import redis as rd
from pymongo import MongoClient
import shutil
from pydantic import BaseModel

client = MongoClient('database', 27017)
database = client['result_database']
image_results = database['image_results']
redis = rd.Redis(host='redis', port=6379)
app = FastAPI()


class ImageResult(BaseModel):
    fileName: str
    hash: str
    result: str

# Must have CORSMiddleware to enable localhost client and server
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5057",
    "http://localhost:5000",
    "http://localhost:6379",
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "PhotoAnalysisServer Running!"}


@app.post("/predict")
async def get_prediction(images: List[UploadFile] = File(...)):
    BUFFER_SIZE = 65536   # Read image data in 64KB Chunks for hashlib
    hashes = {}

    # Process uploaded images
    for upload_file in images:
        f = upload_file.file
        md5 = hashlib.md5()
        while True:
            data = f.read(BUFFER_SIZE)
            if not data:
                break
            md5.update(data)

        # Process image
        image_hash = md5.hexdigest()
        hashes[upload_file.filename] = image_hash


        # Save files to directory ./images/ and the images will automatically be saved locally via Docker
        # The ./images/ folder on the host machine maps to ./server/images/ on Docker
        file_extension = os.path.splitext(upload_file.filename)[1]
        with open("./images/"+image_hash+file_extension, "wb") as buffer:
            shutil.copyfileobj(f, buffer)

        # Store current status of processing job in redis (false=not processed yet)
        redis.set(image_hash, 'false')




    return {"images": [hashes[key] for key in hashes]}


@app.get("/predict/{key}")
async def get_job(key):

    # Check that image exists in system
    if not redis.exists(key):
        return HTTPException(status_code=404, detail="key not found")

    result = redis.get(key)

    return {"status": result}


