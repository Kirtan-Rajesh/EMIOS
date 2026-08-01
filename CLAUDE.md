# EMIOS — Claude Working Notes

Enterprise Migration Intelligence Operating System. See **`README.md`** at the repo root for
the canonical project overview, architecture map, setup steps, and conventions/gotchas —
that file is now the shared source of truth for the whole team (including non-Claude tools
like Kiro), so it's kept in sync deliberately. This file holds Claude-specific working notes
that don't belong in a team-facing README.

## Identity / context
- The user is **Kirtan**, who owns **ingestion, graph, and integration** per the team's task
  guide. Team: Rohan (presentation), Bhargavi (LLM orchestration/agents, remote, uses Kiro),
  Kunal (API contracts), Shweta (frontend).
- **Repo history**: this started in a personal repo (`github.com/Kirtan-Rajesh/EMIOS`, still
  configured as the `origin` remote) with a nested `EMIOS/EMIOS/` layout. On 2026-07-25 the
  team's actual official repo (`github.com/CybHackathon-2026/CDAI_Cortex_Creators`, default
  branch `develop`) became the primary repo going forward. The local working copy was
  flattened (no more `EMIOS/EMIOS/` nesting — `backend/`, `frontend/`, etc. are now direct
  repo-root children) and pushed there. Internal planning docs (`docs/`, proposal PDFs,
  `task.md`, `walkthrough.md`) were deliberately **not** carried over to the official repo —
  their useful content was folded into `README.md` instead. If you're looking for one of those
  old doc files and it's not in this working copy, it was intentionally dropped, not lost.
- There's also a `FolderStructure` branch on the official repo (a teammate's alternate scaffold
  proposal — Alembic migrations, different file layout, Vite/React frontend). It's all empty
  stub files, no real code. Per explicit user instruction: leave it alone, don't merge or adopt
  its layout, our structure is the working baseline.

## Local toolchain status (updated 2026-07-25)
Python 3.12 and Podman are installed. Podman machine: WSL backend, 3 CPU/2GiB — bump if things
run slow with all three DBs up. `podman compose` on Windows delegates to an external compose
provider (found `docker-compose.exe` already present here); a fresh Linux box needs one
installed explicitly (`docker-compose-plugin` recommended — see the Deployment section of
`README.md` for why). Venv lives at repo-root `venv/` (gitignored, along with `*.db` and
`backend/.env*`).

## AWS deployment (successfully validated 2026-07-30 - see scripts/deploy/RUNBOOK.md)

**A full deployment succeeded on 2026-07-30**, on Kirtan's personal AWS account
(`337909785359`, user `emios_deploy`), as a test run ahead of the team's Saturday deploy to the
main account. Instance since torn down (or will be shortly - it's Kirtan's personal account,
not meant to stay live). **`scripts/deploy/RUNBOOK.md` is now the canonical deployment
procedure** - written specifically for the team to follow on Saturday, covering AWS/IAM setup,
credential handling, and (critically) every real issue hit during this deployment with its
fix already applied in-repo. Read it before redeploying; don't re-derive the below from
scratch.

**What got fixed in-repo as a result of this deployment:**
- `bootstrap.sh` / `deploy.sh`: podman 3.4.4 (Ubuntu 22.04's apt default) has no `compose`
  subcommand - both scripts now drive the standalone `docker-compose` binary against
  `DOCKER_HOST=unix:///run/podman/podman.sock` instead of `podman compose`.
- `docker-compose.prod.yml`: switched all three services to `network_mode: host`. podman
  3.4.4's CNI backend turned out to have broken support for compose-managed labeled networks
  (multiple distinct failure modes - see RUNBOOK.md §6.3) that made the socket fix alone
  insufficient; host networking sidesteps the whole problem.
- `deploy.sh`: fixed a tar bug where the packaging step included its own output tarball
  (`tar: file changed as we read it`) and would have shipped `scripts/deploy/.aws_credentials`
  (containing the deploy AWS secret) to the remote instance. Both now excluded.
- `README.md` and `scripts/deploy/README.md` updated to match the fixed commands.

**Two things surfaced during this deployment that are account-specific, not code bugs** (see
RUNBOOK.md §6.1/§6.2 for full detail, don't be surprised if they recur on a different
restricted/new account): a Bedrock-only IAM key silently failed every S3/Lightsail call with no
obvious "this key is scoped down" error; and the account capped Lightsail at the 1GB
`micro_3_0` bundle rather than the intended 4GB, requiring a swap file. Also unexplained:
direct SSH from the deploying machine to the instance never worked despite the instance being
healthy and its firewall correctly open - the Lightsail browser-based SSH console worked
immediately as a workaround. Worth testing early on the main account whether this recurs.

**Credentials**: keep using the `scripts/deploy/.aws_credentials` (gitignored) + inline
`source` pattern described in RUNBOOK.md §4 - not chat, not env vars set in a long-lived shell.
The original exposed key (`AKIA6KXQFANS22TVVW5X`) from the first 2026-07-25 attempt still needs
rotating in IAM if that hasn't happened.

### Separately, already done and merged into the working tree today (not part of the blocker above)
Fixed several bugs found via code review before attempting deploy: blocking event-loop calls
in 5 places (Qdrant init, S3 upload, agent-negotiation LangGraph run, migration-plan LLM call,
document-discovery reads/extraction) now go through `run_in_threadpool`; upload size cap +
extension allowlist added; `JWT_SECRET_KEY` was missing from `docker-compose.prod.yml`'s
backend service entirely (silent auth-bypass risk) — now required via `${JWT_SECRET_KEY:?...}`;
>72-byte passwords no longer 500 on register; simulate/report upsert race condition fixed;
`AssessmentReport.generated_at` no longer bumps on unrelated updates. All 99 backend tests still
pass, frontend still builds clean. Also removed two stale background-agent worktrees (see git
history if curious — they were fully superseded, nothing lost).
