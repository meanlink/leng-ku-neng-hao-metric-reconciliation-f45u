import os

MYSQL = {
    "host": os.getenv("MYSQL_HOST", "db"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "coldstore"),
    "password": os.getenv("MYSQL_PASSWORD", "coldstore_pw"),
    "database": os.getenv("MYSQL_DATABASE", "coldstore"),
    "charset": "utf8mb4",
    "autocommit": True,
}
JWT_SECRET = os.getenv("JWT_SECRET", "coldstore-demo-secret")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
