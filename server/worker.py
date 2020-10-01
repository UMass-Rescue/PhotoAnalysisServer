from redis import Redis
from rq import Queue, Worker

redis = Redis(host='redis', port=6379)
queue = Queue('scene_detection', connection=redis)

if __name__ == '__main__':
    worker = Worker([queue], connection=redis, name='scene_detection')
    worker.work()