# using a resnet 18 model to calculate to predict the scene category, (an
# indoor/outdoor image classifier using the scene category) and the scene 
# attributes of a given input image
import torch
from torch.autograd import Variable as V
import torchvision.models as models
from torchvision import transforms as trn
from torch.nn import functional as F
import os
import sys
import numpy as np
from scipy.misc import imresize as imresize
from PIL import Image

import sqlite3
import json

# from scenedetect.db_utils import create_db, open_db_connection, commit_and_close_connect

## Global Constants
CATEGORIES_PLACES_URL = 'https://raw.githubusercontent.com/csailvision/places365/master/categories_places365.txt'
IO_PLACES_URL = 'https://raw.githubusercontent.com/csailvision/places365/master/IO_places365.txt'
LABELS_SUNATTRIBUTE_URL = 'https://raw.githubusercontent.com/csailvision/places365/master/labels_sunattribute.txt'
SCENE_ATTRIBUTE_WIDERESNET18_URL = 'http://places2.csail.mit.edu/models_places365/W_sceneattribute_wideresnet18.npy'
WIDERESNET18_TAR_URL = 'http://places2.csail.mit.edu/models_places365/'
WIDERESNET18_URL = 'https://raw.githubusercontent.com/csailvision/places365/master/wideresnet.py'

# function to ensure presence of the list of scene categories, list of scene 
# attributes and lookup table of scene category classifying as indoor or 
# outdoor scene
def load_labels():
    # fetching the list of scene categories if not already present
    file_name_category = 'categories_places365.txt'
    if not os.access(file_name_category, os.W_OK):
        os.system('wget ' + CATEGORIES_PLACES_URL)

    # listing all the scene categories in a tuple
    classes = list()
    with open(file_name_category) as class_file:
        for line in class_file:
            classes.append(line.strip().split(' ')[0][3:])
    classes = tuple(classes)

    # fetching the lookup table given an input scene to check if its indoor or
    # outdoor 
    file_name_IO = 'IO_places365.txt'
    if not os.access(file_name_IO, os.W_OK):
        os.system('wget ' + IO_PLACES_URL)

    # listing the table in an array
    with open(file_name_IO) as f:
        lines = f.readlines()
        labels_IO = []
        for line in lines:
            items = line.rstrip().split()
            labels_IO.append(int(items[-1]) -1) # 0 is indoor, 1 is outdoor
    labels_IO = np.array(labels_IO)

    # fetching scene attributes if not already present
    file_name_attribute = 'labels_sunattribute.txt'
    if not os.access(file_name_attribute, os.W_OK):
        os.system('wget ' + LABELS_SUNATTRIBUTE_URL)
    with open(file_name_attribute) as f:
        lines = f.readlines()
        labels_attribute = [item.rstrip() for item in lines]
    file_name_W = 'W_sceneattribute_wideresnet18.npy'
    if not os.access(file_name_W, os.W_OK):
        os.system('wget ' + SCENE_ATTRIBUTE_WIDERESNET18_URL)
    W_attribute = np.load(file_name_W)

    return classes, labels_IO, labels_attribute, W_attribute

'''def returnCAM(feature_conv, weight_softmax, class_idx):
    # generate the class activation maps upsample to 256x256
    size_upsample = (256, 256)
    nc, h, w = feature_conv.shape
    output_cam = []
    for idx in class_idx:
        cam = weight_softmax[class_idx].dot(feature_conv.reshape((nc, h*w)))
        cam = cam.reshape(h, w)
        cam = cam - np.min(cam)
        cam_img = cam / np.max(cam)
        cam_img = np.uint8(255 * cam_img)
        output_cam.append(imresize(cam_img, size_upsample))
    return output_cam
'''

# transforme the image as required by the resnet model
def returnTF():
    tf = trn.Compose([
        trn.Resize((224,224)),
        trn.ToTensor(),
        trn.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])
    return tf

# fetch and load the model, model specified inside the function itself and can
# be modified to load a different model
def load_model(features_blobs):
    # create feature list given module, input and output
    def hook_feature(module, input, output):
        features_blobs.append(np.squeeze(output.data.cpu().numpy()))

	# fetch the pretrained weights of the model if not already present
    model_file = 'wideresnet18_places365.pth.tar'
    if not os.access(model_file, os.W_OK):
        os.system('wget ' + WIDERESNET18_TAR_URL + model_file)
        os.system('wget ' + WIDERESNET18_URL)

    # imported here since this model file may not be present in the beginning
    # and has been downloaded right before this
    # makes the model ready to run the forward pass
    import wideresnet
    model = wideresnet.resnet18(num_classes=365)
    checkpoint = torch.load(model_file, map_location=lambda storage, loc: storage)
    state_dict = {str.replace(k,'module.',''): v for k,v in checkpoint['state_dict'].items()}
    model.load_state_dict(state_dict)
    model.eval()

    # hook the feature extractor
    features_names = ['layer4','avgpool'] # this is the last conv layer of the resnet
    for name in features_names:
        model._modules.get(name).register_forward_hook(hook_feature)
    return model

# the main function which given an input image predicts the scene categories,
# scene attributes and an indoor or outdoor image using the output of the 
# above two
def get_scene_attributes(img_name, file_name):
    # Common list required for hooking features later in the model
    features_blobs = []

    # load the labels
    classes, labels_IO, labels_attribute, W_attribute = load_labels()

    # load the model using all helper functions defined before this
    model = load_model(features_blobs)

    tf = returnTF() 

    # get the softmax weight
    params = list(model.parameters())
    weight_softmax = params[-2].data.numpy()
    weight_softmax[weight_softmax<0] = 0

    # load the test image    
    img = Image.open(img_name)

    if img.mode != 'RGB':        
        img = img.convert("RGB")
    input_img = V(tf(img).unsqueeze(0))

    # forward pass
    logit = model.forward(input_img)
    h_x = F.softmax(logit, 1).data.squeeze()
    probs, idx = h_x.sort(0, True)
    probs = probs.numpy()
    idx = idx.numpy()
    
    # fw.write('RESULT ON ' + img_name + '\n')    

    # output the IO prediction
    io_image = np.mean(labels_IO[idx[:10]]) # vote for the indoor or outdoor
    env_type = ""
    if io_image < 0.5:
        env_type = 'indoor'
    else:
        env_type = 'outdoor'
	
    # output the scene categories
    # fw.write('--SCENE CATEGORIES:')
    scene_categories_dict = {}
    for i in range(0, 5):    
        scene_categories_dict[classes[idx[i]]] = str(probs[i])
        
    scene_categories = json.dumps(scene_categories_dict)

    # output the scene attributes
    responses_attribute = W_attribute.dot(features_blobs[1])
    idx_a = np.argsort(responses_attribute)
    scene_attributes = ', '.join([labels_attribute[idx_a[i]] for i in range(-1,-10,-1)])

    # write the predicted scene categories and attributes in the database
    # conn = open_db_connection()
    # conn.execute("INSERT INTO SCENE_DETECTION (NAME, ENVIRONMENT, CATEGORIES, ATTRIBUTES) \
    #         VALUES (?,?,?,?)", (file_name, env_type, scene_categories, scene_attributes))
    # commit_and_close_connect(conn)

    return {"category_results": scene_categories_dict, "attributes_result": [labels_attribute[idx_a[i]] for i in range(-1,-10,-1)]}
