import os

from dotenv import load_dotenv
from redis import Redis

load_dotenv(verbose=True)


class Settings:
    app_name = os.getenv("APP_NAME", "RIA")
    app_env = os.getenv("APP_ENV", "development")

    browerless_ws = os.getenv("BROWSERLESS_WS", "")

    log_level = os.getenv("LOG_LEVEL", "INFO")

    db_dialect = os.getenv("DB_DIALECT", "postgresql")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", 5432)
    db_database = os.getenv("DB_DATABASE", "")
    db_pgschema = os.getenv("DB_PGSCHEMA", "")
    db_username = os.getenv("DB_USERNAME", "")
    db_password = os.getenv("DB_PASSWORD", "")

    @property
    def db_url(self) -> str:
        if not self.db_database:
            return ""

        return f"{self.db_dialect}://{self.db_username}:{self.db_password}@pgbouncer:{self.db_port}/{self.db_database}"

    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-pro")

    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_region = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")
    aws_bucket = os.getenv("AWS_BUCKET", "")
    aws_s3_presigned_url_expiresin = int(os.getenv("AWS_S3_PRESIGNED_URL_EXPIRESIN", 180))

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))

    @property
    def redis_conn(self):
        return Redis(host=self.redis_host, port=self.redis_port)


settings = Settings()
