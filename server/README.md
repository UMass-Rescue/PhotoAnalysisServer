# PhotoAnalysisServer Webserver
This folder contains the FastAPI webserver used as the core of the PhotoAnalysisServer.

## Getting the Server Up and Running

At this point it is assumed that you have the docker container for this server up and running and are now looking to run the server. You should also have at least one ML model up and running. Instructions for setting up a model can be found [here](https://github.com/CodyRichter/MLMicroserviceTemplate)

### Configure Postman

To test this server, we will be using postman to send our `GET`/`POST` requests. You will need to make an account with the website, but you can download the client [here](https://www.postman.com/downloads/)

### Uploading Image to Server

To upload an image to the server, we will be making a `POST` request to `localhost:5000/predict`

Select the `body` tab right under the `POST` request bar and in that tab, select the `form-data` option. In this field, write in `images` for a key, and make sure you select the value type to be a file so we will be able to upload files to the server. Upload the image or images you want to send to the server for analysis in the value section. 

The other entry you will need to enter is for the models. At the moment, this server only supports running one model at a time, but we are hoping to change that in the near future. For this entry, type `models` into the key entry and the model name into the value entry. For the sake of this example, we are using the template `example_model`.

![](https://i.imgur.com/PxdB3Bq.png)

After filling out the form entries, press the send button to send the POST request to the server. If successful, it will return a hash value similar to the one returned above. Once you have this hash, you can move on to get the prediction results of the model from the server. 

### Getting Prediction Results from Server

![](https://i.imgur.com/Ccfl8RG.png)

To receive the prediction results from the server, you must have the image hash that was returned in the response body of `POST /predict`. Then, you can make a `GET` request to `/predict/<hash>`, where `<hash>` is the hash that was returned.
> **Example:** `GET localhost:5000/predict/a2afb42a1e9d55c9f07669b095a0b4b6` will return a JSON result: `
> {"status": "SUCCEEDED","results": {"someResultCategory": "actualResultValue"}}`


## Current Limitations
- The endpoint `POST /predict` is only able to handle a single model name string in the `models` section of the request body. In the future, this will be expanded to allow for an array of model names to be passed
- If you create multiple predictions for a single image with different models, only the final prediction result will be stored since the key it is saved under is image-specific, not model-specific. 
    - When MongoDB is implemented in the future, the system will be able to track multiple model results for a single image successfully
