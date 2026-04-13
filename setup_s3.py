"""
AWS S3 Bucket Setup Script for Traffic Evidence Storage.

Run once:  python setup_s3.py

What this does:
  1. Creates a private S3 bucket in your region
  2. Blocks all public access (evidence must not be public)
  3. Enables versioning (keeps old versions if a file is overwritten)
  4. Enables AES-256 server-side encryption by default
  5. Sets a lifecycle policy (move to Glacier after 365 days)
  6. Creates an IAM policy document you can attach to your IAM user/role
  7. Optionally creates a CloudFront distribution for fast video streaming
"""

import os
import json
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "traffic-evidence-bucket")
REGION      = os.getenv("AWS_REGION", "ap-south-1")


def get_clients():
    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=REGION,
    )
    return session.client("s3"), session.client("iam"), session.client("cloudfront")


def create_bucket(s3):
    print(f"\n[1/6] Creating S3 bucket: {BUCKET_NAME} in {REGION}")
    try:
        if REGION == "us-east-1":
            s3.create_bucket(Bucket=BUCKET_NAME)
        else:
            s3.create_bucket(
                Bucket=BUCKET_NAME,
                CreateBucketConfiguration={"LocationConstraint": REGION}
            )
        print(f"      Bucket created: s3://{BUCKET_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "BucketAlreadyOwnedByYou":
            print("      Bucket already exists (owned by you). Continuing.")
        else:
            raise


def block_public_access(s3):
    print("\n[2/6] Blocking all public access (private bucket)...")
    s3.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls":       True,
            "IgnorePublicAcls":      True,
            "BlockPublicPolicy":     True,
            "RestrictPublicBuckets": True,
        },
    )
    print("      Public access blocked.")


def enable_versioning(s3):
    print("\n[3/6] Enabling versioning (tamper-evident — keeps all file versions)...")
    s3.put_bucket_versioning(
        Bucket=BUCKET_NAME,
        VersioningConfiguration={"Status": "Enabled"}
    )
    print("      Versioning enabled.")


def enable_encryption(s3):
    print("\n[4/6] Enabling default AES-256 server-side encryption...")
    s3.put_bucket_encryption(
        Bucket=BUCKET_NAME,
        ServerSideEncryptionConfiguration={
            "Rules": [{
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256"
                },
                "BucketKeyEnabled": True,
            }]
        }
    )
    print("      AES-256 encryption enabled.")


def set_lifecycle_policy(s3):
    print("\n[5/6] Setting lifecycle policy (Glacier after 365 days)...")
    lifecycle = {
        "Rules": [
            {
                "ID":     "ArchiveOldEvidence",
                "Status": "Enabled",
                "Filter": {"Prefix": "violations/"},
                "Transitions": [
                    {"Days": 365, "StorageClass": "GLACIER"},
                ],
                "NoncurrentVersionTransitions": [
                    {"NoncurrentDays": 90, "StorageClass": "STANDARD_IA"},
                ],
                "NoncurrentVersionExpiration": {"NoncurrentDays": 730},
            }
        ]
    }
    s3.put_bucket_lifecycle_configuration(
        Bucket=BUCKET_NAME,
        LifecycleConfiguration=lifecycle
    )
    print("      Lifecycle policy set.")


def print_iam_policy():
    print("\n[6/6] IAM Policy (attach this to your IAM user / role):")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid":    "TrafficEvidenceAccess",
                "Effect": "Allow",
                "Action": [
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                    "s3:GetBucketLocation",
                    "s3:CreateMultipartUpload",
                    "s3:UploadPart",
                    "s3:CompleteMultipartUpload",
                    "s3:AbortMultipartUpload",
                ],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET_NAME}",
                    f"arn:aws:s3:::{BUCKET_NAME}/*",
                ]
            }
        ]
    }
    print(json.dumps(policy, indent=2))

    # Save to file
    with open("iam_policy.json", "w") as f:
        json.dump(policy, f, indent=2)
    print("\n      Policy saved to iam_policy.json")
    print("      Attach it in: AWS Console -> IAM -> Users -> Your User -> Add Permissions -> Attach Policy")


def test_upload(s3):
    print("\n[TEST] Uploading test file to verify bucket access...")
    test_content = b"Traffic Violation System - S3 connectivity test"
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key="test/connectivity_check.txt",
        Body=test_content,
        ServerSideEncryption="AES256",
    )
    # Read it back
    resp = s3.get_object(Bucket=BUCKET_NAME, Key="test/connectivity_check.txt")
    assert resp["Body"].read() == test_content
    # Clean up
    s3.delete_object(Bucket=BUCKET_NAME, Key="test/connectivity_check.txt")
    print("      Upload / Download / Delete test PASSED.")


def print_env_config():
    print("\n" + "="*60)
    print("  Add these to your .env file:")
    print("="*60)
    print(f"  STORAGE_BACKEND=s3")
    print(f"  AWS_REGION={REGION}")
    print(f"  S3_BUCKET_NAME={BUCKET_NAME}")
    print(f"  AWS_ACCESS_KEY_ID=<your-key>")
    print(f"  AWS_SECRET_ACCESS_KEY=<your-secret>")
    print("="*60)
    print("\n  Video evidence will be streamed via S3 presigned URLs")
    print("  (6-hour expiry, no public access, AES-256 encrypted)")


def main():
    print("="*60)
    print("  AWS S3 Setup for Traffic Evidence Storage")
    print("="*60)

    s3, iam, cf = get_clients()

    create_bucket(s3)
    block_public_access(s3)
    enable_versioning(s3)
    enable_encryption(s3)
    set_lifecycle_policy(s3)
    print_iam_policy()
    test_upload(s3)
    print_env_config()

    print("\nS3 setup complete! Your evidence bucket is ready.")
    print(f"Bucket: s3://{BUCKET_NAME}")
    print(f"Region: {REGION}")


if __name__ == "__main__":
    main()
