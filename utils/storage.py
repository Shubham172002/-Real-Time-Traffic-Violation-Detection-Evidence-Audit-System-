"""
Evidence file storage abstraction.
Supports local filesystem (dev) and AWS S3 (production).

AWS S3 Setup:
  1. Create bucket: aws s3 mb s3://your-bucket --region ap-south-1
  2. Block all public access (private bucket)
  3. Enable versioning: aws s3api put-bucket-versioning ...
  4. Set STORAGE_BACKEND=s3 in .env
  5. Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME in .env
"""
import os
import uuid
import mimetypes
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

STORAGE_BACKEND  = os.getenv("STORAGE_BACKEND", "local")
LOCAL_PATH       = Path(os.getenv("LOCAL_STORAGE_PATH", "./evidence_files"))
S3_BUCKET        = os.getenv("S3_BUCKET_NAME", "traffic-evidence")
AWS_REGION       = os.getenv("AWS_REGION", "ap-south-1")
CLOUDFRONT_URL   = os.getenv("CLOUDFRONT_URL", "")   # optional CDN prefix

# Max sizes (enforced in upload helpers)
MAX_IMAGE_MB  = int(os.getenv("MAX_IMAGE_MB", "10"))
MAX_VIDEO_MB  = int(os.getenv("MAX_VIDEO_MB", "200"))
MAX_DOC_MB    = int(os.getenv("MAX_DOC_MB", "20"))

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".3gp"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
DOC_EXTENSIONS   = {".pdf", ".doc", ".docx"}


def _get_s3_client():
    import boto3
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=AWS_REGION,
    )


def get_file_category(filename: str) -> str:
    """Return 'video', 'photo', or 'doc' based on extension."""
    ext = Path(filename).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in IMAGE_EXTENSIONS:
        return "photo"
    return "doc"


def validate_file_size(file_bytes: bytes, filename: str) -> Optional[str]:
    """Return error message if file is too large, else None."""
    size_mb = len(file_bytes) / (1024 * 1024)
    cat = get_file_category(filename)
    limits = {"video": MAX_VIDEO_MB, "photo": MAX_IMAGE_MB, "doc": MAX_DOC_MB}
    limit = limits.get(cat, MAX_DOC_MB)
    if size_mb > limit:
        return f"{cat.title()} file too large ({size_mb:.1f} MB). Max allowed: {limit} MB."
    return None


def upload_evidence(file_bytes: bytes, original_filename: str, violation_id: int) -> Tuple[str, str]:
    """
    Upload evidence file and return (file_url, unique_filename).
    For videos, uploads with multipart on S3 for large files.
    """
    ext   = Path(original_filename).suffix.lower()
    cat   = get_file_category(original_filename)
    # Store under: violations/<id>/videos/ or photos/ or docs/
    unique_name = f"violations/{violation_id}/{cat}s/{uuid.uuid4().hex}{ext}"

    if STORAGE_BACKEND == "s3":
        url = _upload_to_s3(file_bytes, unique_name, ext)
    else:
        url = _upload_to_local(file_bytes, unique_name)

    return url, unique_name


def _upload_to_s3(file_bytes: bytes, key: str, ext: str) -> str:
    """Upload to S3 with AES-256 encryption. Uses multipart for videos > 10 MB."""
    import boto3
    from io import BytesIO

    s3      = _get_s3_client()
    ct      = _content_type(ext)
    size_mb = len(file_bytes) / (1024 * 1024)

    if size_mb > 10:
        # Multipart upload for large video files
        mpu  = s3.create_multipart_upload(
            Bucket=S3_BUCKET, Key=key,
            ContentType=ct, ServerSideEncryption="AES256"
        )
        upload_id = mpu["UploadId"]
        chunk_size = 10 * 1024 * 1024   # 10 MB chunks
        parts = []
        buf   = BytesIO(file_bytes)
        part_num = 1
        while True:
            chunk = buf.read(chunk_size)
            if not chunk:
                break
            resp = s3.upload_part(
                Bucket=S3_BUCKET, Key=key,
                PartNumber=part_num, UploadId=upload_id, Body=chunk
            )
            parts.append({"PartNumber": part_num, "ETag": resp["ETag"]})
            part_num += 1
        s3.complete_multipart_upload(
            Bucket=S3_BUCKET, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": parts}
        )
    else:
        s3.put_object(
            Bucket=S3_BUCKET, Key=key,
            Body=file_bytes,
            ContentType=ct,
            ServerSideEncryption="AES256",
        )

    return f"s3://{S3_BUCKET}/{key}"


def _upload_to_local(file_bytes: bytes, unique_name: str) -> str:
    dest = LOCAL_PATH / unique_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(file_bytes)
    return str(dest)


def get_evidence_bytes(file_url: str) -> Optional[bytes]:
    """Download evidence file bytes (for hash verification)."""
    if _is_s3(file_url):
        try:
            s3   = _get_s3_client()
            key  = _s3_key(file_url)
            resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
            return resp["Body"].read()
        except Exception:
            return None
    else:
        path = Path(file_url)
        return path.read_bytes() if path.exists() else None


def generate_presigned_url(file_url: str, expiry_seconds: int = 3600) -> str:
    """
    Generate a time-limited secure URL.
    - S3: presigned URL (works for videos too — browser streams directly)
    - CloudFront: signed URL if CLOUDFRONT_URL is set
    - Local: return file path
    """
    if _is_s3(file_url):
        key = _s3_key(file_url)
        if CLOUDFRONT_URL:
            # Use CloudFront URL (set up signed URLs separately if private distribution)
            return f"{CLOUDFRONT_URL.rstrip('/')}/{key}"
        s3 = _get_s3_client()
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=expiry_seconds,
        )
    return file_url


def get_video_stream_url(file_url: str) -> Optional[str]:
    """
    Return a URL suitable for video streaming.
    S3 presigned URLs work directly with HTML5 <video> and st.video().
    Local: return the file path (Streamlit can read local paths).
    """
    if _is_s3(file_url):
        # 6-hour expiry for video streaming sessions
        return generate_presigned_url(file_url, expiry_seconds=21600)
    # Local — return path if exists
    path = Path(file_url)
    if path.exists():
        return str(path)
    return None


def delete_evidence(file_url: str) -> bool:
    try:
        if _is_s3(file_url):
            s3 = _get_s3_client()
            s3.delete_object(Bucket=S3_BUCKET, Key=_s3_key(file_url))
        else:
            path = Path(file_url)
            if path.exists():
                path.unlink()
        return True
    except Exception:
        return False


def get_s3_bucket_stats() -> dict:
    """Return storage stats for the S3 bucket (admin use)."""
    try:
        s3  = _get_s3_client()
        cw  = __import__("boto3").client("cloudwatch", region_name=AWS_REGION)
        from datetime import datetime, timedelta
        resp = cw.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName="BucketSizeBytes",
            Dimensions=[
                {"Name": "BucketName",  "Value": S3_BUCKET},
                {"Name": "StorageType", "Value": "StandardStorage"},
            ],
            StartTime=datetime.utcnow() - timedelta(days=2),
            EndTime=datetime.utcnow(),
            Period=86400,
            Statistics=["Average"],
        )
        datapoints = resp.get("Datapoints", [])
        size_bytes = datapoints[-1]["Average"] if datapoints else 0
        paginator = s3.get_paginator("list_objects_v2")
        count = sum(
            page.get("KeyCount", 0)
            for page in paginator.paginate(Bucket=S3_BUCKET)
        )
        return {
            "bucket": S3_BUCKET,
            "region": AWS_REGION,
            "object_count": count,
            "size_gb": round(size_bytes / (1024 ** 3), 3),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_s3(url: str) -> bool:
    return STORAGE_BACKEND == "s3" or url.startswith("s3://")


def _s3_key(url: str) -> str:
    return url.replace(f"s3://{S3_BUCKET}/", "")


def _content_type(ext: str) -> str:
    ct, _ = mimetypes.guess_type(f"file{ext}")
    if ct:
        return ct
    fallback = {
        ".mp4": "video/mp4", ".avi": "video/x-msvideo",
        ".mov": "video/quicktime", ".mkv": "video/x-matroska",
        ".webm": "video/webm", ".3gp": "video/3gpp",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".pdf": "application/pdf",
    }
    return fallback.get(ext, "application/octet-stream")
