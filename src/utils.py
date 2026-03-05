import hashlib


def hash_url(normalized_url: str) -> str:
    return hashlib.sha256(
        normalized_url.encode("utf-8")
    ).hexdigest()
