# Deploy scripts

**See `RUNBOOK.md` in this directory for the full deployment procedure** — AWS/IAM
setup, credential handling, known issues and their fixes (several were hit and
resolved during the first real deployment on 2026-07-30), and a troubleshooting
index. This file is just a quick reference for what each script does.

Prepared 2026-07-25. Nothing here creates any AWS resources until you actually run
`provision.py`.

## Order of operations

```bash
# 1. Create the S3 bucket + Lightsail instance (few minutes; instance boots and
#    installs podman/compose in the background via cloud-init).
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
    venv/Scripts/python.exe scripts/deploy/provision.py

# 2. Ship the current code, generate secrets, bring the stack up, health-check it.
#    Re-run this any time you want to redeploy latest code - it's idempotent and
#    reuses the same secrets after the first run.
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
    bash scripts/deploy/deploy.sh

# 3. End of day / done demoing: delete the instance so it stops accruing cost.
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
    venv/Scripts/python.exe scripts/deploy/teardown.py
```

Requires the `emios_policy` IAM policy attached to the key's user (S3 bucket
admin/object rw on `emios-documents`, Lightsail instance lifecycle, Bedrock
invoke - see the policy discussion earlier in the deploy conversation).

**No Lightsail instance available, or prefer plain EC2?** Swap step 1/3 for
`provision_ec2.py` / `teardown_ec2.py` (needs the policy's `EC2Lifecycle`
statement, see `RUNBOOK.md` §3.2/§5.1). Step 2 (`deploy.sh`) is unchanged either
way - see `RUNBOOK.md` §5.1's EC2 subsection for the full writeup.

## What each script does

- **provision.py** - creates (or reuses) the `emios-documents` S3 bucket with
  public access blocked/versioning/encryption on, creates an SSH key pair
  (private key saved locally, gitignored), picks the cheapest Ubuntu 22.04
  Lightsail bundle with >= 4GB RAM, launches the instance with `bootstrap.sh` as
  its cloud-init userData, opens port 8000, and writes `.deploy_state.json` for
  the next steps to read.
- **bootstrap.sh** - runs once as root on first boot; installs podman + a
  docker-compose-v2-compatible CLI (apt package, falling back to the standalone
  binary) + git.
- **deploy.sh** - waits for SSH + bootstrap to finish, generates
  `backend/.env.production` (fresh JWT secret, Postgres/Neo4j passwords, this
  session's AWS key if still set in your shell) on first run, tars up the repo
  (excluding `.git`, `venv`, `node_modules`, caches, local `storage_fallback/`, and
  its own generated/gitignored files - see `RUNBOOK.md` §6.5), ships it over, and
  runs `docker-compose -f docker-compose.prod.yml --env-file backend/.env.production
  up -d --build` against podman's Docker-API-compatible socket (not `podman compose`
  - see `RUNBOOK.md` §6.3), then polls `/api/health`.
- **teardown.py** - deletes the instance + key pair (the actual cost driver per
  the README's own budget note). Leaves the S3 bucket alone by default since it
  holds your uploaded documents; pass `--delete-bucket` to remove that too.
- **provision_ec2.py** / **teardown_ec2.py** - EC2 equivalents of the two
  scripts above, for when Lightsail isn't the right fit. Launches a `t3.medium`
  Ubuntu 22.04 instance (default VPC, a dedicated security group opening TCP
  22/8000) running the same `bootstrap.sh`; writes the same `.deploy_state.json`
  shape `deploy.sh` already reads, so step 2 doesn't change at all.

## Notes / things to reconsider tomorrow

- `deploy.sh` bakes this shell's `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` into
  `backend/.env.production` on the box (the fallback path `docker-compose.prod.yml`
  already supports). The project's own docs prefer an IAM role attached to the
  instance instead so no long-lived key sits on a public server - worth doing if
  there's time, not required to get deployed.
- The access key used for all of this has been posted in this chat's transcript
  more than once earlier today - rotate it in IAM before/after tomorrow's deploy
  if that hasn't happened yet.
- `provision.py` is safe to re-run (skips bucket/instance creation if they
  already exist) but doesn't handle "instance exists with a different
  config than expected" - if a deploy goes sideways, easiest fix is
  `teardown.py` then `provision.py` again rather than trying to patch state.
