# PhotoAnalysisServer 

This is a server designed to handle and dispatch requests to machine learning models, and then return the prediction results to clients. A queue system is utilized.


## Overview
A client can post a request which contains the images and what models he wants to run the analysis on the images. The servers then verify the model names. If all the models are present, a md5 hash is generated for each image which is its unique identifier for the image which is used to track its status throughout the pipeline. These hashes are returned to the client as a response to the post request. 

Once the hash is generated, the image is stored on the server in the docker volume. A job id is then created which is an image, model pair i.e. each job id contains information to access the image and what model to run on said image. 

The Job IDs are stored in redis and they are put in a job queue using redis queue. Once an ML microservice is done working on a job, the redis will reflect that. The status of the job can be accessed through a get request using the image key(the hash). 

---

## Initial Setup

To run this application, there are some commands that must be run. All of these should be done via the command line in the root directory of the project folder.
Ensure that you have Docker running on your computer before attempting these commands

#### Configure Server:

You will need to give the correct ports and model names for each MLMicroserviceTemplate that is loaded. They can be set in the setings class on line 25 of main.py
```python=
class Settings(BaseSettings):
    available_models = {
        "model_name": 5005,
        "another_model_name": 5006,
    }
```

#### Set up Application with Docker

##### [Step 1] Build Docker Container
Download dependencies with Docker and build container
```
docker-compose build
```

##### [Step 2] Start Docker Container
Start application
```
docker-compose up
```

---

## Project Architecture
![](https://i.imgur.com/z4WX9v0.png)


## Development Information

- When working with MLMicroserviceTemplate models, if there are any changed made to the model itself, the PhotoAnalysisServer must also be restarted before it is able to interact with the modified model.
- For more in-depth information on interacting with the server, see the `README.md` in the `./server/` directory.

### Postman API Information 
[![Run in Postman](https://run.pstmn.io/button.svg)](https://app.getpostman.com/run-collection/8ae4299e6f600505577c)