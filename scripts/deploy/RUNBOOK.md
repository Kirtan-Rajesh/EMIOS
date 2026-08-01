# EMIOS AWS Deployment Runbook

Written 2026-07-30 after a full successful deployment to a personal/test AWS account.
This is the reference for redeploying to the team's main AWS account (planned for
Saturday) — it captures not just the happy path but every real problem hit along the
way, since several of them are near-certain to recur on a fresh account/instance.

**Read section 6 (Known Issues) before you start.** Most of the pain in the first
deployment was podman/CNI networking bugs that are now already fixed in this repo
(`docker-compose.prod.yml`, `bootstrap.sh`, `deploy.sh`) — you shouldn't have to
re-discover them, but you should know they're there if something looks familiar.

---

## 1. What gets deployed

Three containers on a single Lightsail VM, all on `network_mode: host` (see §6.3 for
why) — no compose-managed bridge network:

| Container | Image | Port | Purpose |
|---|---|---|---|
| `emios-postgres` | `postgres:16-alpine` | 5432 | Relational data (assessments, uploads, waves) |
| `emios-neo4j` | `neo4j:5.12.0` (+apoc) | 7474 (HTTP), 7687 (Bolt) | Digital-twin graph store |
| `emios-backend` | built from `backend/Dockerfile` (repo-root build context) | 8000 | FastAPI app, serves the built React frontend too |

Qdrant is intentionally **not** deployed — nothing in the codebase queries it, and
skipping it saves RAM on a small instance.

Supporting AWS resources: one S3 bucket (document storage), one Lightsail instance,
one Lightsail SSH key pair, one IAM user with a scoped policy.

---

## 2. Local prerequisites (on whoever's machine runs the deploy)

- Python 3.11+ with the repo's `venv/` set up (`pip install -r backend/requirements.txt`,
  plus `boto3` for the deploy scripts specifically)
- `git`, `ssh`, `scp`, `tar` on PATH (Git Bash provides all of these on Windows)
- An AWS account you can create an IAM user in (see §3 — **do not** reuse a
  Bedrock-only/restricted key for this, see §6.1)

---

## 3. AWS account setup

### 3.1 Create a dedicated IAM user for deployment

Console → **IAM → Users → Create user**. Name it `emios-deploy`. **Don't** grant AWS
Management Console access — programmatic access only.

### 3.2 Attach a scoped policy

Console → **IAM → Policies → Create policy → JSON**, paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3EmiosBuckets",
      "Effect": "Allow",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::emios-*",
        "arn:aws:s3:::emios-*/*"
      ]
    },
    {
      "Sid": "LightsailLifecycle",
      "Effect": "Allow",
      "Action": "lightsail:*",
      "Resource": "*"
    },
    {
      "Sid": "EC2Lifecycle",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeImages",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:CreateKeyPair",
        "ec2:DeleteKeyPair",
        "ec2:DescribeKeyPairs",
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:DescribeSecurityGroups",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BedrockInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ListFoundationModels"
      ],
      "Resource": "*"
    }
  ]
}
```

The `EC2Lifecycle` statement is only needed if you're using `provision_ec2.py` /
`teardown_ec2.py` instead of the Lightsail scripts (see §5.1 below) - safe to
include either way since it's scoped to actions, not a specific instance.

Name it `emios_deploy_policy`, create it, then attach it to `emios-deploy`
(**Permissions → Add permissions → Attach policies directly**). The `emios-*`
wildcard on the S3 resource matters — bucket names are globally unique across *all*
AWS accounts, so whatever exact bucket name you end up using (see §4.1), a wildcard
means you won't have to edit this policy again to match it.

### 3.3 Generate the access key

User page → **Security credentials** tab → **Create access key** → use case
**"Command Line Interface (CLI)"** → **Create**. Copy both values immediately — the
secret is shown exactly once.

**Copy-paste carefully.** A single mistyped character in the secret produces
`SignatureDoesNotMatch` on every single API call with no way to tell which character
is wrong — the whole secret is either byte-for-byte correct or it isn't. If you're
not 100% sure the copy was clean, don't debug it — just delete that key and generate
a fresh one (§3.3 again).

### 3.4 Sanity-check the key before doing anything else

```bash
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... venv/Scripts/python.exe -c "
import boto3
print(boto3.client('sts', region_name='us-east-1').get_caller_identity())
"
```

Confirm the `Account` in the output is actually the main team account, and the `Arn`
is the `emios-deploy` user you just made. This 10-second check would have saved a lot
of time in the first deployment (see §6.1).

---

## 4. Handling credentials — do this, not chat/Slack

**Never paste AWS keys into a chat window, issue tracker, or shared doc** — even a
"private" one. The first deployment's key ended up in a chat transcript multiple
times and had to be rotated as a result.

Instead:
1. Create `scripts/deploy/.aws_credentials` (already gitignored — check `.gitignore`
   has `scripts/deploy/.aws_credentials` before trusting this) with:
   ```
   AWS_ACCESS_KEY_ID=AKIA...
   AWS_SECRET_ACCESS_KEY=...
   ```
   No quotes needed (harmless if present), no spaces around `=`.
2. Source it inline when running deploy commands, never `export` it into a
   long-lived shell:
   ```bash
   set -a && source scripts/deploy/.aws_credentials && set +a && <command>
   ```
3. If working with an AI assistant/pair on this, ask it to read credentials directly
   from that file rather than having them typed into the conversation — that keeps
   the secret out of any chat log entirely.

---

## 5. Deployment procedure

### 5.1 Provision the S3 bucket + Lightsail instance

```bash
set -a && source scripts/deploy/.aws_credentials && set +a
S3_BUCKET_NAME=emios-documents-<something-unique> venv/Scripts/python.exe scripts/deploy/provision.py
```

Pick a bucket name that's actually available — `emios-documents` alone may already be
taken globally (it was, by the first test account). Appending the AWS account ID is
an easy way to guarantee uniqueness, e.g. `emios-documents-<account-id>`.

**If this fails with `InvalidInputException: ... can not create an instance using
this Lightsail plan size`**, the account is capped below the default 4GB
(`medium_3_0`) bundle — see §6.2. Retry with a smaller size:
```bash
S3_BUCKET_NAME=... LIGHTSAIL_MIN_RAM_GB=2 venv/Scripts/python.exe scripts/deploy/provision.py   # or 1, or 0.5
```

This writes `scripts/deploy/.deploy_state.json` (gitignored) and saves the SSH
private key to `scripts/deploy/emios-lightsail-key.pem` (gitignored). Note the
public IP it prints.

#### Alternative: provision on EC2 instead of Lightsail

If Lightsail isn't an option (e.g. no instance available, or you'd rather use
plain EC2), `provision_ec2.py` does the same job — same `.deploy_state.json`
output shape, same `bootstrap.sh` cloud-init script, same `deploy.sh` afterwards
(it doesn't care which provisioner wrote the state file). Needs the
`EC2Lifecycle` IAM statement from §3.2.

```bash
set -a && source scripts/deploy/.aws_credentials && set +a
S3_BUCKET_NAME=emios-documents-<something-unique> venv/Scripts/python.exe scripts/deploy/provision_ec2.py
```

Picks the latest Ubuntu 22.04 AMI, launches a `t3.medium` (4GB/2vCPU — override
with `EC2_INSTANCE_TYPE`) in the account's default VPC/subnet, creates a security
group opening TCP 22 + 8000, and saves the key to
`scripts/deploy/emios-prod-ec2-key.pem`. Tear it down with `teardown_ec2.py`
(§5.5), not `teardown.py` — they key off `.deploy_state.json`'s `platform` field
and will refuse to run against the wrong provisioner's state.

### 5.2 Ship code and bring the stack up

```bash
set -a && source scripts/deploy/.aws_credentials && set +a
bash scripts/deploy/deploy.sh
```

This waits for SSH, waits for the cloud-init bootstrap (~1-3 min: installs podman,
docker-compose, enables `podman.socket`), generates `backend/.env.production` with
fresh random JWT/Postgres/Neo4j secrets (reused on repeat runs), ships a tarball of
the repo, and runs `docker-compose ... up -d --build` on the instance via
`DOCKER_HOST=unix:///run/podman/podman.sock` (not `podman compose` — see §6.3).

**If `deploy.sh` hangs or times out waiting for SSH**, don't assume it'll eventually
connect — see §6.4 for the fallback manual procedure, which is what the first
deployment actually had to use end-to-end.

### 5.3 Verify

```bash
curl http://<public-ip>:8000/api/health
# expect: {"status":"healthy","database":"connected","api":"online"}
```

Also load `http://<public-ip>:8000/` in a browser to confirm the frontend serves.

### 5.4 Redeploying after code changes

Re-run `deploy.sh` — it's idempotent, reuses the existing `.env.production` secrets
(no data loss), re-ships the latest tarball, and rebuilds/restarts the stack.

### 5.5 Tearing down

```bash
set -a && source scripts/deploy/.aws_credentials && set +a
venv/Scripts/python.exe scripts/deploy/teardown.py       # if provisioned via provision.py (Lightsail)
venv/Scripts/python.exe scripts/deploy/teardown_ec2.py    # if provisioned via provision_ec2.py (EC2)
```

Both leave the S3 bucket alone by default (pass `--delete-bucket` to remove it
too) and both delete `.deploy_state.json` when done, so the next `provision*.py`
run starts clean.

---

## 6. Known issues (already fixed in-repo, but good to recognize if they resurface)

### 6.1 Restricted/sandboxed AWS keys silently fail everything downstream

If an access key belongs to an account/user provisioned specifically for something
narrow (e.g. a hackathon "Bedrock-only" credential), it can fail `s3:CreateBucket`,
`lightsail:CreateInstances`, even `iam:GetUser` on itself — with no single error that
says "this key is scoped down." Symptom: `403 Forbidden` on `HeadBucket` even though
the bucket doesn't exist yet, or `AccessDenied` on `CreateBucket` even after attaching
a policy that should cover it. **Always run the §3.4 identity check before spending
time on IAM policy edits.**

### 6.2 Lightsail instance size caps

Some accounts (new accounts, restricted/sandboxed accounts) cap the largest Lightsail
bundle they'll allow, independent of IAM permissions — you'll see
`InvalidInputException: Sorry, your account can not create an instance using this
Lightsail plan size`. `provision.py` respects `LIGHTSAIL_MIN_RAM_GB` to pick a smaller
bundle (see §5.1). If capped at 1GB (`micro_3_0`), **add a swap file** before running
`docker-compose up --build` — building the backend's Python image plus running
Postgres + Neo4j + the app in 1GB RAM alone risks OOM kills mid-deploy:
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

### 6.3 podman 3.4.4 has no `compose` subcommand, and its CNI networking is broken for compose-managed networks

Ubuntu 22.04's apt repo installs podman 3.4.4; the `compose` subcommand was added in
podman 4.x. **Already fixed**: `bootstrap.sh` installs a standalone `docker-compose`
v2 binary and enables `podman.socket`; `deploy.sh` and `docker-compose.prod.yml`'s own
header comment both point at driving `docker-compose` against
`DOCKER_HOST=unix:///run/podman/podman.sock` instead of `podman compose`.

That gets you past the missing-subcommand problem, but a second, nastier issue
follows: podman 3.4.4's CNI network backend doesn't reliably support the labels
docker-compose uses to recognize "networks I created." Symptoms seen, in order, while
chasing this:
- `CNI network "X_default" not found` when starting a container, right after compose
  reports the network as `Created`
- Manually creating the network via `podman network create` **without** labels
  succeeds, but then compose refuses to use it: `network exists but was not created
  by compose ... incorrect label com.docker.compose.network set to ""`
- Creating it again **with** `--label com.docker.compose.network=default` reports
  success, but an immediate `podman network inspect` says `no such network` — labeled
  network creation is simply broken on this podman/CNI combination
- Even when a network conflist file does get generated by compose, it's written with
  `cniVersion: "1.0.0"`, which podman 3.4.4's bundled `firewall` CNI plugin rejects
  outright: `plugin firewall does not support config version "1.0.0"`

**The fix already in this repo**: `docker-compose.prod.yml` uses
`network_mode: host` on all three services instead of a custom bridge network. This
sidesteps podman's CNI networking entirely — services reach each other via
`localhost` (see the `NEO4J_URI`/`DATABASE_URL` values in that file), which is a
reasonable simplification for a single-VM deployment with no need for network
isolation between containers. **If you're redeploying with this repo as-is, you
should not hit any of the above** — this section is here so if a future change
reintroduces a custom network, you recognize this class of failure and know to
either avoid it (host networking) or upgrade podman to 4.x+ instead (see the
alternative fix discussed in `README.md`'s deployment section).

### 6.4 Direct SSH from a deploy machine may be blocked even though the instance is healthy

In the first deployment, the Lightsail instance was confirmed `running` via the AWS
API with all three ports (22/80/8000) open in its firewall config, but was
**completely unreachable** (`Connection timed out`) from the deploying machine on
every port, for 45+ minutes — while outbound SSH to other hosts (e.g. `github.com:22`)
worked fine from the same machine, ruling out a local firewall issue. A traceroute to
the instance died without ever getting a response past an ISP backbone hop.

The Lightsail **browser-based SSH console** (Console → Lightsail → instance →
"Connect using SSH") worked immediately despite this — it routes through AWS's own
infrastructure rather than the public internet path. **If `deploy.sh` can't reach the
instance and this recurs**, don't keep waiting — check the browser console, and if it
connects, be prepared to do the deploy manually through it instead of via `deploy.sh`:
1. In the browser terminal: `git clone -b <branch> <repo-url> ~/emios`
2. Create `~/emios/backend/.env.production` with the same fields `deploy.sh` would
   generate (see that script's heredoc for the template) — for a manual deploy,
   generate the JWT/Postgres/Neo4j secrets locally first
   (`python -c "import secrets;print(secrets.token_urlsafe(24))"`) since you don't
   have a shell on the box to do it
3. Run the same `docker-compose ... up -d --build` command §5.2 describes
4. **If pasting multi-line/large content into that browser terminal silently drops
   data** (file ends up truncated/unchanged even though the paste appeared to work),
   break it into chunks of a few hundred bytes each and verify the line count after
   each paste (`wc -l <file>`) before proceeding — this was necessary to reliably
   transfer even a single config file in the first deployment.

### 6.5 `deploy.sh`'s tarball used to include itself (and your AWS secret)

**Already fixed.** The packaging step now explicitly excludes
`scripts/deploy/emios-deploy.tar.gz` (was causing `tar: file changed as we read it`
failures — the tarball was including itself mid-write) and
`scripts/deploy/.aws_credentials` / `.deploy_state.json` / `.env.production.generated`
(were being shipped to the remote instance unnecessarily, `.aws_credentials`
critically so — that file holds the deploy key, which has no business sitting on a
public-facing box). If you ever hand-roll a similar tar command, remember: exclude
the output file itself, and exclude anything in `scripts/deploy/` that isn't meant
for the server.

---

## 7. Environment variables reference (`backend/.env.production`)

`deploy.sh` generates this automatically (fresh random secrets, reused on repeat
deploys) — this table is for anyone building it by hand per §6.4's manual path, or
just auditing what's in there:

| Variable | Source | Notes |
|---|---|---|
| `PORT` | fixed `8000` | |
| `POSTGRES_USER` / `POSTGRES_DB` | fixed `emios` | |
| `POSTGRES_PASSWORD` | generated | `secrets.token_urlsafe(24)` |
| `NEO4J_PASSWORD` | generated | `secrets.token_urlsafe(24)` |
| `JWT_SECRET_KEY` | generated | `secrets.token_urlsafe(48)` — **must not** be left at the source-controlled dev default; `docker-compose.prod.yml` enforces this with `${JWT_SECRET_KEY:?...}` |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | optional, blank by default | only needed for those specific LLM fallback paths |
| `AWS_REGION` | `us-east-1` default | |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | **leave blank** unless you specifically need Bedrock LLM calls live | see below |
| `BEDROCK_LLM_MODEL_ID` | `nvidia.nemotron-nano-12b-v2` default | override per `backend/app/core/config.py`'s comments if using a Claude model via inference profile |
| `S3_BUCKET_NAME` | from `.deploy_state.json` | must match what `provision.py` actually created |
| `ENABLE_LANGFUSE_TRACING` | `false` | needs a self-hosted/cloud Langfuse project to be worth turning on |

**On the AWS credentials specifically**: leaving them blank means Bedrock-backed LLM
calls fall back to deterministic agent behavior (app still runs fine, just no live
model reasoning). If you want live LLM calls, use a **separate, narrowly-scoped**
Bedrock-invoke-only key here — not the `emios-deploy` key from §3, which has
broader S3/Lightsail rights that shouldn't sit on a public-facing instance's disk.

---

## 8. Teardown / cost management

```bash
set -a && source scripts/deploy/.aws_credentials && set +a
venv/Scripts/python.exe scripts/deploy/teardown.py
```

Deletes the Lightsail instance + SSH key pair (the actual cost driver — bills
hourly). Leaves the S3 bucket and its contents alone unless you pass
`--delete-bucket`. Run this at the end of any demo/testing session that isn't meant
to stay live — Lightsail bills continuously while the instance exists, regardless of
whether anyone's using it.

---

## 9. Quick troubleshooting index

| Symptom | See |
|---|---|
| `403 Forbidden` / `AccessDenied` on S3 or Lightsail calls that should be allowed | §6.1 |
| `InvalidInputException: ... can not create an instance using this Lightsail plan size` | §6.2 |
| `Error: unrecognized command 'podman compose'` | §6.3 |
| `CNI network "X_default" not found` | §6.3 |
| `network ... was not created by compose` / label errors | §6.3 |
| `plugin firewall does not support config version` | §6.3 |
| Instance shows `running` but every port times out from your machine | §6.4 |
| `tar: file changed as we read it` | §6.5 |
| `SignatureDoesNotMatch` on any AWS call | §3.3 — regenerate the key, don't debug the string |
