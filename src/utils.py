import hashlib

import boto3

from botocore.config import Config

from .settings import settings


def hash_url(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.aws_access_key,
    aws_secret_access_key=settings.aws_secret_key,
    region_name=settings.aws_region,
    config=Config(
        retries={
            "total_max_attempts": 3,
            "mode": "adaptive",
        }
    ),
)
