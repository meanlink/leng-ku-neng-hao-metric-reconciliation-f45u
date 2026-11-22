import os, time
from pathlib import Path
import redis
from src.config import REDIS_URL

path = Path("/app/artifacts/worker-heartbeat")
client = redis.from_url(REDIS_URL)
while True:
    client.set("coldstore:worker:heartbeat", str(time.time()), ex=30)
    path.write_text(str(time.time()))
    time.sleep(5)
