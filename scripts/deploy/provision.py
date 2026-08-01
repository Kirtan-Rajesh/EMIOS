"""Step 1 of tomorrow's deploy: creates the S3 bucket and the Lightsail instance.

Run from the repo root with the project venv, credentials via env vars (never
hardcode them here):

    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
        venv/Scripts/python.exe scripts/deploy/provision.py

Requires the `emios_policy` IAM policy (S3 bucket admin/object rw on
`emios-documents`, Lightsail instance lifecycle, Bedrock invoke) attached to the
key's user. Idempotent-ish: safe to re-run if it fails partway (skips bucket
creation if it already exists; instance creation still needs a fresh name if an
instance from a prior attempt is still around - see teardown.py).

Writes scripts/deploy/.deploy_state.json with everything deploy.py needs next
(instance name/IP, key pair path, bucket name) - gitignored, local only.
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
REPO_ROOT = HERE.parent.parent
STATE_FILE = HERE / ".deploy_state.json"
KEY_FILE = HERE / "emios-lightsail-key.pem"
BOOTSTRAP_SCRIPT = HERE / "bootstrap.sh"

REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "emios-documents")
INSTANCE_NAME = os.environ.get("LIGHTSAIL_INSTANCE_NAME", "emios-prod")
KEY_PAIR_NAME = os.environ.get("LIGHTSAIL_KEY_PAIR_NAME", "emios-prod-key")
MIN_RAM_GB = float(os.environ.get("LIGHTSAIL_MIN_RAM_GB", "4"))


def get_session() -> boto3.Session:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        sys.exit(
            "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY must be set in the environment "
            "(don't hardcode them in this file or pass them as plain args)."
        )
    return boto3.Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=REGION)


def ensure_bucket(s3) -> None:
    print(f"--- S3 bucket '{BUCKET_NAME}' ---")
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
        print("Already exists, skipping creation.")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code not in ("404", "NoSuchBucket"):
            raise
        create_kwargs = {"Bucket": BUCKET_NAME}
        if REGION != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": REGION}
        s3.create_bucket(**create_kwargs)
        print("Created.")

    s3.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_versioning(Bucket=BUCKET_NAME, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_encryption(
        Bucket=BUCKET_NAME,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    s3.put_bucket_tagging(Bucket=BUCKET_NAME, Tagging={"TagSet": [{"Key": "project", "Value": "emios"}]})
    print("Public access blocked, versioning + SSE-S3 encryption enabled.")


def ensure_key_pair(lightsail) -> None:
    print(f"--- Lightsail key pair '{KEY_PAIR_NAME}' ---")
    if KEY_FILE.exists():
        print(f"Private key already saved at {KEY_FILE}, reusing.")
        return
    try:
        resp = lightsail.create_key_pair(keyPairName=KEY_PAIR_NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidInputException" and "already exists" in str(e):
            sys.exit(
                f"Key pair '{KEY_PAIR_NAME}' already exists in Lightsail but "
                f"{KEY_FILE} is missing locally - the private key can't be retrieved "
                f"after creation. Delete the key pair in Lightsail (or pick a new "
                f"LIGHTSAIL_KEY_PAIR_NAME) and re-run."
            )
        raise
    KEY_FILE.write_text(resp["privateKeyBase64"])
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass  # best-effort on Windows
    print(f"Saved private key to {KEY_FILE}")


def pick_blueprint(lightsail) -> str:
    for bp in lightsail.get_blueprints()["blueprints"]:
        if bp["platform"] == "LINUX_UNIX" and bp["blueprintId"] == "ubuntu_22_04":
            return bp["blueprintId"]
    sys.exit("Could not find the ubuntu_22_04 blueprint - check `lightsail.get_blueprints()` output.")


def pick_bundle(lightsail) -> str:
    candidates = [
        b
        for b in lightsail.get_bundles()["bundles"]
        if b["ramSizeInGb"] >= MIN_RAM_GB
        and "LINUX_UNIX" in b["supportedPlatforms"]
        # Skip "*_ipv6_*" bundles - deploy.sh/ssh/curl all target publicIpAddress
        # (IPv4); avoid any ambiguity about whether that field is populated on
        # an IPv6-focused bundle by just not picking one.
        and "ipv6" not in b["bundleId"]
    ]
    if not candidates:
        sys.exit(f"No Lightsail bundle with >= {MIN_RAM_GB}GB RAM found.")
    cheapest = min(candidates, key=lambda b: b["price"])
    print(
        f"--- Bundle: {cheapest['bundleId']} "
        f"({cheapest['ramSizeInGb']}GB RAM, {cheapest['cpuCount']} vCPU, "
        f"${cheapest['price']}/mo cap) ---"
    )
    return cheapest["bundleId"]


def create_instance(lightsail, blueprint_id: str, bundle_id: str) -> None:
    print(f"--- Lightsail instance '{INSTANCE_NAME}' ---")
    existing = lightsail.get_instances().get("instances", [])
    if any(i["name"] == INSTANCE_NAME for i in existing):
        print("Already exists, skipping creation.")
        return

    az = f"{REGION}a"
    user_data = BOOTSTRAP_SCRIPT.read_text()
    lightsail.create_instances(
        instanceNames=[INSTANCE_NAME],
        availabilityZone=az,
        blueprintId=blueprint_id,
        bundleId=bundle_id,
        keyPairName=KEY_PAIR_NAME,
        userData=user_data,
        tags=[{"key": "project", "value": "emios"}],
    )
    print(f"Create requested in {az}. Waiting for it to reach 'running' state...")

    for _ in range(60):
        state = lightsail.get_instance_state(instanceName=INSTANCE_NAME)["state"]["name"]
        print(f"  state: {state}")
        if state == "running":
            break
        time.sleep(10)
    else:
        sys.exit("Instance did not reach 'running' within 10 minutes - check the Lightsail console.")


def open_port(lightsail) -> None:
    print("--- Opening port 8000 (app) ---")
    # open_instance_public_ports is additive - it does not remove the default
    # SSH(22) rule Lightsail applies to new instances, unlike put_instance_public_ports.
    lightsail.open_instance_public_ports(
        instanceName=INSTANCE_NAME,
        portInfo={"fromPort": 8000, "toPort": 8000, "protocol": "tcp"},
    )


def save_state(public_ip: str, bundle_id: str) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {
                "instance_name": INSTANCE_NAME,
                "region": REGION,
                "public_ip": public_ip,
                "key_pair_name": KEY_PAIR_NAME,
                "key_file": str(KEY_FILE),
                "bucket_name": BUCKET_NAME,
                "bundle_id": bundle_id,
            },
            indent=2,
        )
    )
    print(f"\nState saved to {STATE_FILE}")


def main() -> None:
    session = get_session()
    s3 = session.client("s3")
    lightsail = session.client("lightsail")

    ensure_bucket(s3)
    ensure_key_pair(lightsail)
    blueprint_id = pick_blueprint(lightsail)
    bundle_id = pick_bundle(lightsail)
    create_instance(lightsail, blueprint_id, bundle_id)
    open_port(lightsail)

    instance = lightsail.get_instance(instanceName=INSTANCE_NAME)["instance"]
    public_ip = instance["publicIpAddress"]
    save_state(public_ip, bundle_id)

    print(f"\nInstance is up at {public_ip}.")
    print("cloud-init bootstrap (podman + compose) runs in the background - give it a")
    print("minute or two, then run scripts/deploy/deploy.sh to ship the code and start the stack.")


if __name__ == "__main__":
    main()
