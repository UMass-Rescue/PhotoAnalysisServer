import requests


def get_model_prediction(host, port, filename):
    args = {'filename': filename}
    print('POST URL:' + 'http://'+host+':'+str(port)+'/predict')
    result = requests.post('http://'+host+':'+str(port)+'/predict', params=args).json()['result']
    return result
