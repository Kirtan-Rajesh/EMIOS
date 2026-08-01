"""EC2 counterpart to teardown.py. Run this when you're done for the day - the
real cost risk is forgetting to terminate the instance, same as with Lightsail.

    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
        venv/Scripts/python.exe scripts/deploy/teardown_ec2.py [--delete-bucket]

Default: terminates the EC2 instance, deletes its security group and key pair.
The S3 bucket (has your uploaded documents in it) is left alone unless you pass
--delete-bucket.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / ".deploy_state.json"


def main() -> None:
    if not STATE_FILE.exists():
        sys.exit(f"No {STATE_FILE} - nothing to tear down (or provision_ec2.py never ran).")

    state = json.loads(STATE_FILE.read_text())
    if state.get("platform") != "ec2":
        sys.exit(
            f"{STATE_FILE} was written by the Lightsail provisioner, not provision_ec2.py "
            f"- use teardown.py instead."
        )

    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        sys.exit("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY must be set in the environment.")

    session = boto3.Session(
        aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=state["region"]
    )
    ec2 = session.client("ec2")

    instance_id = state["instance_id"]
    print(f"--- Terminating instance '{state['instance_name']}' ({instance_id}) ---")
    try:
        ec2.terminate_instances(InstanceIds=[instance_id])
        print("Terminate requested, waiting for it to finish...")
        ec2.get_waiter("instance_terminated").wait(InstanceIds=[instance_id])
    except ClientError as e:
        print(f"(skipping - {e.response['Error']['Code']})")

    sg_id = state.get("security_group_id")
    if sg_id:
        print(f"--- Deleting security group '{sg_id}' ---")
        # The ENI behind the instance can take a few seconds to fully release after
        # termination, which would otherwise fail this with DependencyViolation.
        for attempt in range(6):
            try:
                ec2.delete_security_group(GroupId=sg_id)
                break
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "InvalidGroup.NotFound":
                    break
                if code == "DependencyViolation" and attempt < 5:
                    time.sleep(10)
                    continue
                print(f"(skipping - {code})")
                break

    print(f"--- Deleting key pair '{state['key_pair_name']}' ---")
    try:
        ec2.delete_key_pair(KeyName=state["key_pair_name"])
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
    print("\nDone. Re-run provision_ec2.py to stand a fresh instance back up.")


if __name__ == "__main__":
    main()
