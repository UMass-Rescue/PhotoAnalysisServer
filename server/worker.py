from redis import Redis
from rq import Queue, Worker

redis = Redis(host='redis', port=6379)
queue = Queue('model_prediction', connection=redis)

if __name__ == '__main__':
    print('Starting Worker')
    worker = Worker([queue], connection=redis, name='model_prediction')
    worker.work()
    print('Ending Worker')
