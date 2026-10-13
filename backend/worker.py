"""Background worker: `python worker.py` consumes the 'documents' queue."""
import os

from redis import Redis
from rq import Queue, Worker

if __name__ == "__main__":
    url = os.environ["REDIS_URL"]
    conn = Redis.from_url(url)
    Worker([Queue("documents", connection=conn)], connection=conn).work()
