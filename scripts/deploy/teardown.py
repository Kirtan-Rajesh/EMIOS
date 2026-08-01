"""End-of-day cleanup. Per the project README's own budget note, the real cost
risk with Lightsail isn't the hourly rate - it's forgetting to delete the
instance. Run this when you're done for the day.

    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
        venv/Scripts/python.exe scripts/deploy/teardown.py [--delete-bucket]

Default: deletes the Lightsail instance and its key pair. The S3 bucket (has
your uploaded documents in it) is left alone unless you pass --delete-bucket.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / ".deploy_state.json"


def main() -> None:
    if not STATE_FILE.exists():
        sys.exit(f"No {STATE_FILE} - nothing to tear down (or provision.py never ran).")

    state = json.loads(STATE_FILE.read_text())
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        sys.exit("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY must be set in the environment.")

    session = boto3.Session(
        aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=state["region"]
    )
    lightsail = session.client("lightsail")

    print(f"--- Deleting instance '{state['instance_name']}' ---")
    try:
        lightsail.delete_instance(instanceName=state["instance_name"])
        print("Delete requested.")
    except ClientError as e:
        print(f"(skipping - {e.response['Error']['Code']})")

    print(f"--- Deleting key pair '{state['key_pair_name']}' ---")
    try:
        lightsail.delete_key_pair(keyPairName=state["key_pair_name"])
    except ClientError as e:
        print(f"(skipping - {e.response['Error']['Code']})")

    key_file = Path(state["key_file"])
    if key_file.exists():
        key_file.unlink()
        print(f"Removed local {key_file}")

    if "--delete-bucket" in sys.argv:
        s3 = session.client("s3")
        bucket = state["bucket_name"]
        print(f"--- Emptying and deleting bucket '{bucket}' ---")
        paginator = s3.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket):
            objects = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in page.get("Versions", [])]
            objects += [{"Key": m["Key"], "VersionId": m["VersionId"]} for m in page.get("DeleteMarkers", [])]
            if objects:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
        s3.delete_bucket(Bucket=bucket)
        print("Bucket deleted.")
    else:
        print(f"\nBucket '{state['bucket_name']}' left in place (has your uploaded documents).")
        print("Re-run with --delete-bucket to remove it too.")

    STATE_FILE.unlink()
    print("\nDone. Re-run provision.py tomorrow to stand a fresh instance back up.")


if __name__ == "__main__":
    main()
