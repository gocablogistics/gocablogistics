# scripts/redis_keepalive.py
import os
import sys
import redis

def main():
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        print("REDIS_URL not set")
        sys.exit(1)

    client = redis.from_url(redis_url, socket_connect_timeout=10)

    client.set("keepalive:heartbeat", "ok", ex=60 * 60 * 24 * 7)
    value = client.get("keepalive:heartbeat")

    print(f"Keepalive OK — value read back: {value}")

if __name__ == "__main__":
    main()