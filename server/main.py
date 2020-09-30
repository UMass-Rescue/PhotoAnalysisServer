from typing import List

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import redis
import fastapi_plugins

app = FastAPI()

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
    # connect to redis
    client = redis.Redis(host='redis', port=6379)

    # set a key
    client.set('test-key', 'test-value')

    # get a value
    value = client.get('test-key')
    return {"message": value}


@app.get("/predict")
async def get_prediction():
    pass