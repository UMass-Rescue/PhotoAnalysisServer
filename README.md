# PhotoAnalysisServer

![Test Cases](https://github.com/UMass-Rescue/PhotoAnalysisServer/workflows/CI/badge.svg)


[![codecov](https://codecov.io/gh/UMass-Rescue/PhotoAnalysisServer/branch/master/graph/badge.svg?token=5RBKQG064N)](https://codecov.io/gh/UMass-Rescue/PhotoAnalysisServer)


This is a server designed to handle and dispatch requests to machine learning models, and then return the prediction results to clients. A queue system is utilized.


## Overview
A client can post a request which contains the images and what models he wants to run the analysis on the images. The servers then verify the model names. If all the models are present, a md5 hash is generated for each image which is its unique identifier for the image which is used to track its status throughout the pipeline. These hashes are returned to the client as a response to the post request.

Once the hash is generated, the image is stored on the server in the docker volume. A job id is then created which is an image, model pair i.e. each job id contains information to access the image and what model to run on said image.

The Job IDs are stored in redis and they are put in a job queue using redis queue. Once an ML microservice is done working on a job, the redis will reflect that. The status of the job can be accessed through a get request using the image key(the hash).

---

## Initial Setup

To run this application, there are some commands that must be run. All of these should be done via the command line in the root directory of the project folder.


#### Set up Application with Docker
Ensure that you have Docker running on your computer before attempting these commands

#### Microservices:

Prediction and training microservices will automatically be registered to the server once
they are started. Microservices must also use an API key that is registered for a specific
microservice type.

Use the following API endpoint with Postman or the client to generate the keys:
`POST /auth/key`

See the [[Postman Endpoint Collection]](https://app.getpostman.com/run-collection/8ae4299e6f600505577c) for more information.

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

- The server will automatically restart when changes are made for development, and changes to
  associated microservices will automatically be propagated to the server.
- For more in-depth information on interacting with the server, see the `README.md` in the `./server/` directory.

### API Information

To get the full functionality from the server, you should use the client or postman instead
of python to call endpoint methods.

Postman is an exceptional tool for testing, calling, and debugging API endpoints. To help
your development, you may download the collection of pre-made endpoints with their associated
parameters.

[![Run in Postman](https://run.pstmn.io/button.svg)](https://app.getpostman.com/run-collection/8ae4299e6f600505577c)
