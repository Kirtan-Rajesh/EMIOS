"""EC2 alternative to provision.py, for when Lightsail isn't available/wanted.
Creates the S3 bucket, a security group, a key pair, and an EC2 instance running
the same bootstrap.sh cloud-init script - deploy.sh works against either
provisioner unchanged, since it only reads .deploy_state.json for public_ip,
key_file, and bucket_name.

Run from the repo root with the project venv, credentials via env vars (never
hardcode them here):

    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
        venv/Scripts/python.exe scripts/deploy/provision_ec2.py

Requires the emios_deploy_policy IAM policy extended with an EC2 statement (see
RUNBOOK.md) on top of the S3/Bedrock statements it already has. Idempotent-ish:
safe to re-run if it fails partway (skips bucket/security-group/instance creation
if they already exist by name/tag; re-run teardown_ec2.py first if you want a
clean slate instead).

Writes scripts/deploy/.deploy_state.json with everything deploy.sh needs next
(same schema provision.py writes, plus instance_id/security_group_id for
teardown_ec2.py) - gitignored, local only.
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
KEY_FILE = HERE / "emios-prod-ec2-key.pem"
BOOTSTRAP_SCRIPT = HERE / "bootstrap.sh"

REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "emios-documents")
INSTANCE_NAME = os.environ.get("EC2_INSTANCE_NAME", "emios-prod")
KEY_PAIR_NAME = os.environ.get("EC2_KEY_PAIR_NAME", "emios-prod-ec2-key")
SG_NAME = os.environ.get("EC2_SECURITY_GROUP_NAME", "emios-prod-sg")
INSTANCE_TYPE = os.environ.get("EC2_INSTANCE_TYPE", "t3.medium")
ROOT_VOLUME_GB = int(os.environ.get("EC2_ROOT_VOLUME_GB", "20"))
UBUNTU_OWNER_ID = "099720109477"  # Canonical


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


def ensure_key_pair(ec2) -> None:
    print(f"--- EC2 key pair '{KEY_PAIR_NAME}' ---")
    if KEY_FILE.exists():
        print(f"Private key already saved at {KEY_FILE}, reusing.")
        return
    try:
        resp = ec2.create_key_pair(KeyName=KEY_PAIR_NAME, KeyType="rsa", KeyFormat="pem")
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidKeyPair.Duplicate":
            sys.exit(
                f"Key pair '{KEY_PAIR_NAME}' already exists in EC2 but {KEY_FILE} is "
                f"missing locally - the private key can't be retrieved after creation. "
                f"Delete the key pair in the EC2 console (or pick a new "
                f"EC2_KEY_PAIR_NAME) and re-run."
            )
        raise
    # newline="" prevents Path.write_text's platform newline translation, which on
    # Windows turns AWS's \n line endings into \r\n and corrupts the PEM (ssh/openssl
    # reject it, and the corruption silently carries through any copy-paste of the
    # file, e.g. into a CI secret).
    KEY_FILE.write_text(resp["KeyMaterial"], newline="")
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass  # best-effort on Windows
    print(f"Saved private key to {KEY_FILE}")


def pick_ubuntu_ami(ec2) -> tuple[str, str]:
    print("--- Looking up latest Ubuntu 22.04 AMI ---")
    resp = ec2.describe_images(
        Owners=[UBUNTU_OWNER_ID],
        Filters=[
            {"Name": "name", "Values": ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]},
            {"Name": "root-device-type", "Values": ["ebs"]},
            {"Name": "virtualization-type", "Values": ["hvm"]},
        ],
    )
    images = resp.get("Images", [])
    if not images:
        sys.exit("No Ubuntu 22.04 AMI found - check region/filters.")
    latest = max(images, key=lambda i: i["CreationDate"])
    print(f"Using {latest['ImageId']} ({latest['Name']})")
    return latest["ImageId"], latest["RootDeviceName"]


def get_default_vpc_subnet(ec2) -> tuple[str, str]:
    print("--- Default VPC/subnet ---")
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        sys.exit(
            "No default VPC in this account/region - create one or pass an explicit "
            "subnet (not currently supported by this script)."
        )
    vpc_id = vpcs[0]["VpcId"]
    subnets = ec2.describe_subnets(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}, {"Name": "default-for-az", "Values": ["true"]}]
    )["Subnets"]
    if not subnets:
        sys.exit(f"No default subnet found in VPC {vpc_id}.")
    subnet_id = subnets[0]["SubnetId"]
    print(f"VPC {vpc_id}, subnet {subnet_id}")
    return vpc_id, subnet_id


def ensure_security_group(ec2, vpc_id: str) -> str:
    print(f"--- Security group '{SG_NAME}' ---")
    existing = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [SG_NAME]}, {"Name": "vpc-id", "Values": [vpc_id]}]
    )["SecurityGroups"]
    if existing:
        print("Already exists, skipping creation.")
        return existing[0]["GroupId"]

    resp = ec2.create_security_group(
        GroupName=SG_NAME,
        Description="EMIOS backend - SSH + app port",
        VpcId=vpc_id,
        TagSpecifications=[
            {"ResourceType": "security-group", "Tags": [{"Key": "project", "Value": "emios"}]}
        ],
    )
    sg_id = resp["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            {"IpProtocol": "tcp", "FromPort": 8000, "ToPort": 8000, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        ],
    )
    print(f"Created {sg_id}, opened TCP 22 + 8000.")
    return sg_id


def create_instance(ec2, ami_id: str, root_device: str, subnet_id: str, sg_id: str) -> str:
    print(f"--- EC2 instance '{INSTANCE_NAME}' ---")
    existing = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [INSTANCE_NAME]},
            {"Name": "instance-state-name", "Values": ["pending", "running"]},
        ]
    )
    reservations = existing.get("Reservations", [])
    if reservations:
        instance_id = reservations[0]["Instances"][0]["InstanceId"]
        print(f"Already exists ({instance_id}), skipping creation.")
        return instance_id

    user_data = BOOTSTRAP_SCRIPT.read_text()
    resp = ec2.run_instances(
        ImageId=ami_id,
        InstanceType=INSTANCE_TYPE,
        MinCount=1,
        MaxCount=1,
        KeyName=KEY_PAIR_NAME,
        UserData=user_data,
        BlockDeviceMappings=[
            {
                "DeviceName": root_device,
                "Ebs": {"VolumeSize": ROOT_VOLUME_GB, "VolumeType": "gp3", "DeleteOnTermination": True},
            }
        ],
        NetworkInterfaces=[
            {
                "DeviceIndex": 0,
                "SubnetId": subnet_id,
                "Groups": [sg_id],
                "AssociatePublicIpAddress": True,
            }
        ],
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": INSTANCE_NAME}, {"Key": "project", "Value": "emios"}],
            }
        ],
    )
    instance_id = resp["Instances"][0]["InstanceId"]
    print(f"Launch requested ({instance_id}). Waiting for it to reach 'running' state...")
    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
    return instance_id


def save_state(instance_id: str, security_group_id: str, public_ip: str) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {
                "platform": "ec2",
                "instance_name": INSTANCE_NAME,
                "instance_id": instance_id,
                "security_group_id": security_group_id,
                "region": REGION,
                "public_ip": public_ip,
                "key_pair_name": KEY_PAIR_NAME,
                "key_file": str(KEY_FILE),
                "bucket_name": BUCKET_NAME,
                "instance_type": INSTANCE_TYPE,
            },
            indent=2,
        )
    )
    print(f"\nState saved to {STATE_FILE}")


def main() -> None:
    session = get_session()
    s3 = session.client("s3")
    ec2 = session.client("ec2")

    ensure_bucket(s3)
    ensure_key_pair(ec2)
    ami_id, root_device = pick_ubuntu_ami(ec2)
    vpc_id, subnet_id = get_default_vpc_subnet(ec2)
    sg_id = ensure_security_group(ec2, vpc_id)
    instance_id = create_instance(ec2, ami_id, root_device, subnet_id, sg_id)

    instance = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
    public_ip = instance["PublicIpAddress"]
    save_state(instance_id, sg_id, public_ip)

    print(f"\nInstance is up at {public_ip}.")
    print("cloud-init bootstrap (podman + compose) runs in the background - give it a")
    print("minute or two, then run scripts/deploy/deploy.sh to ship the code and start the stack.")


if __name__ == "__main__":
    main()
