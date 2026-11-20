"""R2 storage is S3-compatible. Upload media only, never credentials or private drafts."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from .util import env, retry_call, secure_https_url, sha256


def upload_audio(file: Path, slug: str) -> dict:
    import boto3
    from botocore.config import Config

    base = secure_https_url(env("R2_PUBLIC_BASE_URL").rstrip("/"))
    account_id = env("R2_ACCOUNT_ID")
    bucket = env("R2_BUCKET")
    digest = sha256(file.read_bytes())
    key = f"episodes/{slug}/{digest[:20]}.mp3"
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(retries={"max_attempts": 4, "mode": "standard"}),
    )
    try:
        client.head_object(Bucket=bucket, Key=key)
    except client.exceptions.ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") not in (403, 404):
            raise
        # HEAD may be prohibited by a limited token; upload safely overwrites same content.
        def upload():
            with file.open("rb") as stream:
                client.upload_fileobj(stream, bucket, key, ExtraArgs={
                    "ContentType": "audio/mpeg", "CacheControl": "public, max-age=31536000, immutable"
                })
        retry_call(upload, label="R2 upload", retry_if=lambda exc: not isinstance(exc, ValueError))
    url = f"{base}/{quote(key, safe='/')}"
    return {"audio_url": url, "audio_sha256": digest, "audio_bytes": file.stat().st_size, "storage_key": key}
