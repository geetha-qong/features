# AWS QA Environment — Design Spec

> **Subsystem B of 2** (paired with `2026-05-29-deliverables-editable-and-admin-view-design.md`). Independent — can ship in parallel.

**Date:** 2026-05-29
**Branch:** `feature/digital-twin`
**Author:** Claude (controller) for tarun

---

## Goal

Stand up a new AWS-hosted QA environment at `https://qa.qongsystems.com` that mirrors today's GCP `dev.qongsystems.com` exactly, so the `feature/digital-twin` branch (and the spec-A app work) can be validated against a real customer-facing URL without touching the existing GCP dev instance and its data.

Once QA proves stable, the same image is promoted to `dev.qongsystems.com` on AWS, and GCP is decommissioned.

## Why

- `feature/digital-twin` has 14 commits ahead of `dev` (model swaps, Vite tile proxy, AccountMenu, %PDF- magic byte, deliverable reorder, +56-field index, admin port). Deploying directly to `dev.qongsystems.com` is risky — existing customers are using it for valve list extraction in production today.
- Moving to AWS gives us redundancy and prepares for the eventual `app.qongsystems.com` production environment without the multi-day all-at-once migration that scared us off in past attempts.
- Doing QA → dev → prod in three flips, each behind a DNS record, lets us validate each step in isolation and roll back trivially.

## Non-Goals

- **Production environment (`app.qongsystems.com`).** Not in this spec. Future work after QA + dev are stable on AWS.
- **AWS-native managed services (RDS, ElastiCache, ECS Fargate).** Explicit non-goal. User prefers cloud-agnostic for portability and cost.
- **Decommissioning GCP.** Happens AFTER dev migrates to AWS, in a separate PR.
- **Multi-region / HA.** Single AZ is fine for QA.
- **Auto-scaling.** One EC2 instance.

---

## Constraints

1. **Cloud-agnostic.** Everything except the EC2 instance, EBS volume, ALB, and ACM must be portable. DNS is on Cloudflare (already vendor-neutral). No RDS, no ElastiCache, no ECS, no SQS, no Secrets Manager (use docker `env_file` populated from SSM Parameter Store at deploy time — see Secrets section).
2. **Cost-conscious.** Target: under $60/month for QA. (One `t3.medium` = ~$30; EBS 50GB gp3 = ~$4; ALB = ~$18; total ~$52.)
3. **Same docker-compose.yml as GCP dev.** No QA-specific compose. Override via `docker-compose.override.qa.yml` only for QA-specific port bindings (e.g., dropping Tailscale on QA).
4. **Zero impact on current GCP dev.** Customers using `dev.qongsystems.com` see no behavior change while we set this up.
5. **Domain.** `qa.qongsystems.com` — CNAME in Cloudflare DNS pointing at the AWS ALB. Orange-cloud (proxy) **OFF** — must be DNS-only mode, otherwise CF proxy + ACM cert collide.
6. **may26aws PROD RULES apply.** Account `449901518037` is treated as production. Every AWS mutation needs same-turn user approval. Verify identity with `aws sts get-caller-identity --profile tnbqong` before any `create-*` / `put-*` / `update-*` call. No `--force`, no `--skip-final-snapshot`.

---

## Architecture

```
                   ┌─────────────────────────────────────────────┐
                   │   Route53                                    │
                   │   qa.qongsystems.com  →  AWS ALB             │
                   │   dev.qongsystems.com →  GCP VM (unchanged)  │
                   └─────────────────────────────────────────────┘
                                          │
                                          ▼
                   ┌─────────────────────────────────────────────┐
                   │   AWS ALB (HTTPS:443, redirects HTTP:80)     │
                   │   ACM cert for qa.qongsystems.com            │
                   └─────────────────────────────────────────────┘
                                          │
                                          ▼
                   ┌─────────────────────────────────────────────┐
                   │   EC2 instance (t3.medium, Ubuntu 24.04)     │
                   │   Security group: 443 from ALB, 22 from SSM  │
                   │   IAM role: SSM access, S3 read (uploads)    │
                   │                                              │
                   │   docker-compose up -d :                     │
                   │     - nginx (8080 internal)                  │
                   │     - web (FastAPI)                          │
                   │     - worker (RQ)                            │
                   │     - postgres (data on EBS mount)           │
                   │     - redis (data on EBS mount)              │
                   │     - minio  (uploads on EBS mount)          │
                   │     - label-studio (annotation tooling)      │
                   │                                              │
                   │   /mnt/qong-data  ←  EBS gp3 50GB            │
                   │     ├── postgres/                            │
                   │     ├── redis/                               │
                   │     ├── minio/                               │
                   │     └── job_outputs/                         │
                   └─────────────────────────────────────────────┘
                                          ▲
                                          │ git pull + docker compose up
                   ┌─────────────────────────────────────────────┐
                   │  GitHub Actions: .github/workflows/         │
                   │  deploy-qa.yml                              │
                   │  Trigger: push to feature/digital-twin      │
                   │  Method: SSH via SSM Session Manager        │
                   └─────────────────────────────────────────────┘
```

---

## Components

### 1. EC2 Instance

- **Type:** `t3.medium` (2 vCPU, 4 GB RAM). Matches GCP dev sizing.
- **AMI:** Ubuntu Server 24.04 LTS — **`ami-0c54f8b78468b2ba2`** (the AMI already in use by `i-0326414bf17cdae36` hermes).
- **Region:** `ap-south-1` (Mumbai), AZ `ap-south-1a` to keep EBS attach simple.
- **Storage:** 30 GB gp3 encrypted root volume for OS + docker images; 50 GB gp3 encrypted EBS volume mounted at `/mnt/qong-data` for app data.
- **Access:** SSM Session Manager only (no public port 22, no SSH keys). Matches hermes-agent / GPU-host pattern in this account.
- **IAM Role:** **reuse `may26-ec2-ssm-role`** — already exists with `AmazonSSMManagedInstanceCore`, `CloudWatchAgentServerPolicy`, and the `may26-parameter-store-read` inline policy granting `ssm:GetParameter*` on `/may26aws/*` + `kms:Decrypt`. No new IAM role needed; just reuse the existing instance profile.
- **IMDS:** v2 required (`HttpTokens=required`, `HttpPutResponseHopLimit=2`) — matches account convention.

### 2. Networking

- **VPC:** Default VPC **`vpc-0c9453aafa64f6e40`** (172.31.0.0/16) — already shared by hermes + GPU. No new VPC.
- **Subnets:** Three public subnets exist; we use two for ALB and place EC2 in `subnet-0eecf25001fad5cc9` (ap-south-1a).
  - `subnet-0eecf25001fad5cc9` (ap-south-1a, 172.31.32.0/20) — EC2 here
  - `subnet-0e6616f423210bbe6` (ap-south-1b, 172.31.0.0/20) — ALB here
  - `subnet-0be74990d09f828d6` (ap-south-1c, 172.31.16.0/20) — ALB here
- **Security Groups (NEW — do not reuse `sg-06e5c4ffda8304d6d` which is egress-only + Ollama-specific):**
  - `qong-qa-alb-sg`: inbound 443/80 from `0.0.0.0/0`. Outbound: to `qong-qa-ec2-sg:8080` only.
  - `qong-qa-ec2-sg`: inbound 8080 from `qong-qa-alb-sg` only. No public ports. Outbound: all (for docker pulls, OpenRouter API, etc.).
- **ALB:** Application Load Balancer, two-AZ (1b + 1c), single target group → EC2:8080 on `subnet-0eecf25001fad5cc9` (1a).
- **ACM cert:** `qa.qongsystems.com` issued via **DNS validation in Cloudflare** (user adds the CNAME). Cert lives in ACM `ap-south-1`.

### 3. DNS (Cloudflare)

`qongsystems.com` is on Cloudflare. Two records the user adds:

1. **ACM validation CNAME** — emitted by `aws acm request-certificate`. Looks like `_<hash>.qa.qongsystems.com → _<hash>.<acm-region>.acm-validations.aws`. Add as a normal CNAME, **orange-cloud OFF** (must be DNS-only). Stays in place forever so the cert auto-renews.
2. **`qa.qongsystems.com` → ALB DNS name** (e.g., `qong-qa-alb-12345.ap-south-1.elb.amazonaws.com`). **Orange-cloud OFF.** Why: with proxy ON, Cloudflare terminates TLS with its own cert and re-encrypts to the origin — our ACM cert never sees the request, breaking validation. DNS-only mode passes the SNI through cleanly.
- **DNS for `dev.qongsystems.com`** unchanged — still points to GCP VM IP.

### 4. Application (docker compose)

Reuse the existing `docker-compose.yml` verbatim. QA-specific concerns handled by:

- **`.env.qa`** — committed `.env.qa.example`, real `.env.qa` lives on the instance only (not in git), populated during initial bootstrap. Same key set as GCP dev's `.env` (OPENROUTER_API_KEY, SECRET_KEY, LS_API_KEY, DATABASE_URL pointing at local postgres container, etc.).
- **`docker-compose.override.qa.yml`** — small override file (committed) that drops any GCP/Tailscale-only port bindings. EC2 has no Tailscale; the ALB is the only ingress.

### 5. Persistent Data on EBS

The EBS volume is mounted at `/mnt/qong-data` and contains:

```
/mnt/qong-data/
├── postgres/         ← postgres container's data volume
├── redis/            ← redis container's data volume (low importance, can lose)
├── minio/            ← uploads (S3-compatible bucket data)
└── job_outputs/      ← processed PDF outputs, CSVs, annotated PDFs
```

`docker-compose.yml` already supports binding host paths via env vars (or we add a small override). Surviving EC2 termination requires the EBS volume to be detached, NOT the instance's root volume.

### 6. Secrets

- **Method:** SSM Parameter Store (free for standard params). Bootstrap script reads SSM at deploy time and renders `.env.qa` on the instance.
- **Why not Secrets Manager:** $0.40/secret/month adds up; SSM standard params are free and sufficient for QA.
- **Why not committed `.env`:** never commit secrets.
- **Namespace:** **`/may26aws/qong-qa/*`** — matches the account's existing convention (other services live under `/may26aws/<service>/`). The `may26-parameter-store-read` inline policy on `may26-ec2-ssm-role` already permits the instance to read this namespace.
- **Param names** (created at provisioning, user fills in values):
  - `/may26aws/qong-qa/openrouter-api-key` (SecureString)
  - `/may26aws/qong-qa/secret-key` (SecureString, FastAPI JWT signing)
  - `/may26aws/qong-qa/ls-api-key` (SecureString, Label Studio)
  - `/may26aws/qong-qa/postgres-password` (SecureString)
  - `/may26aws/qong-qa/minio-root-user` + `/may26aws/qong-qa/minio-root-password` (SecureString)

### 7. Deploy Pipeline

**File:** `.github/workflows/deploy-qa.yml`

**Trigger:** `push` to `feature/digital-twin` (later: rename to `qa` branch if cleaner).

**Steps:**
1. Checkout
2. Configure AWS credentials (GitHub Actions OIDC → IAM role)
3. Invoke SSM `RunCommand` on the QA instance:
   ```
   cd /opt/qong
   git fetch origin feature/digital-twin
   git checkout feature/digital-twin
   git pull
   docker compose build web worker
   docker compose up -d
   docker compose exec -T web python3 -m alembic upgrade head  # or migration script
   ```
4. Wait for health-check on `https://qa.qongsystems.com/healthz` (must already return 200).
5. Notify Slack (existing webhook) on success/failure.

**Why SSM, not SSH:** no public SSH port, no key management in GitHub Secrets. Same pattern Anthropic and most security-conscious orgs use.

### 8. Backups

Reuse the GCP backup pattern (`scripts/backup.sh` + `.github/workflows/backup.yml`). Modifications:

- Backup target: S3 bucket `qong-qa-backups` (cheap; lifecycle policy auto-deletes >30 days).
- Schedule: nightly at 02:00 UTC.
- What's backed up: postgres dump + `job_outputs/` tarball + `minio/` tarball.

QA backups are low-importance (QA data is reproducible). Schedule them so we have the *workflow* tested before dev migration, not because we care about the data.

### 9. Health Check Endpoint

`/healthz` already exists (verify in `webapp/main.py`). ALB uses it for target group health. If missing, add: returns 200 + `{"status": "ok"}` after a trivial DB ping.

---

## Data Flow (Day 1 setup)

```
Engineer (you)
   │
   ├─ Terraform / aws-cli: create VPC bits, EC2, EBS, ALB, ACM, Route53 record, SSM params, IAM
   ├─ SSH (via SSM Session Manager) into the EC2
   ├─ Bootstrap script: apt install docker; mount EBS; clone repo; render .env.qa from SSM; docker compose up -d
   ├─ Verify https://qa.qongsystems.com loads + health check passes
   └─ Push to feature/digital-twin → GitHub Actions auto-deploys
```

Subsequent deploys are automatic on push.

---

## IaC Approach

**Recommendation: hand-rolled `aws` CLI scripts in `infra/aws-qa/`**, not Terraform.

Why:
- One-time setup, small scope (~12 resources). Terraform's value comes from change management over time; for a single-shot QA setup it's overhead.
- The user wants speed today.
- We can lift-and-shift to Terraform/Pulumi when we stand up production.

**Files we'll create:**
```
infra/aws-qa/
├── README.md                    ← setup walkthrough
├── 01-create-vpc-resources.sh   ← idempotent: create or describe security groups
├── 02-launch-ec2.sh             ← create EBS, EC2, attach, mount
├── 03-create-alb.sh             ← TG, ALB, listener, ACM
├── 04-create-dns.sh             ← Route53 record
├── 05-bootstrap-instance.sh     ← run on the EC2 to set up docker + clone repo
├── 06-deploy.sh                 ← used by GitHub Actions, idempotent
└── ssm-params.sh                ← list/set SSM parameters
```

Every script is idempotent (check-then-create). Re-running them is safe.

---

## Error Handling

| Failure | Response |
|---|---|
| ACM cert validation pending | wait + retry; cert validation can take 5-30 min |
| EBS attach fails (already attached) | script detects + continues |
| Health check fails after deploy | rollback: `git checkout HEAD~1 && docker compose up -d` triggered by GH Action on red health check |
| SSM param missing | bootstrap aborts with clear error; user runs `ssm-params.sh set` |
| DNS not propagating | wait; verify with `dig qa.qongsystems.com @8.8.8.8` |

---

## Testing

**Pre-deploy:**
- `docker compose config` validates the override file syntax.
- Lint shell scripts with `shellcheck`.

**Smoke after deploy:**
1. `curl -fsS https://qa.qongsystems.com/healthz` returns 200.
2. Sign up a test user; upload a known PDF (one from `ref/`); confirm job completes and CSV downloads.
3. Verify backups by waiting for next nightly run and confirming S3 object size > 0.

**Soak test (Day 2-7):**
- Run `feature/digital-twin` through the QA env for a week — every feature in spec A gets exercised on QA before the dev migration.
- Watch CloudWatch metrics: CPU < 60% sustained, RAM < 80%, disk I/O reasonable.

---

## Migration Plan (QA → dev cutover, future)

After QA is stable for ~1 week:

1. Stand up a second EC2 + EBS in the SAME AWS setup, give it the same configuration but pointed at a fresh DB.
2. Run a one-off `pg_dump` from GCP dev → restore to AWS new instance.
3. Sync `job_outputs/` via `rsync` from GCP to AWS EBS.
4. Switch `dev.qongsystems.com` Route53 record from GCP VM to the new AWS ALB (or new dev ALB).
5. Watch for 24h, then decommission GCP.

This migration is OUT OF SCOPE for the current spec — captured here only so the QA design accommodates it without rework.

---

## Cost Estimate (Monthly, USD)

| Item | Spec | Cost |
|---|---|---|
| EC2 t3.medium | on-demand, 24/7 | ~$30 |
| EBS gp3 root (30 GB) | 30 × $0.08 | ~$2.40 |
| EBS gp3 data (50 GB) | 50 × $0.08 | ~$4 |
| ALB | 730 hrs + LCU | ~$18 |
| ACM cert | free | $0 |
| Route53 hosted zone (if new) | $0.50/mo | $0.50 |
| S3 backups (10 GB) | $0.023/GB | $0.23 |
| SSM standard params | free | $0 |
| Data transfer (outbound, modest) | 50 GB | ~$4.50 |
| **Total** | | **~$59/mo** |

Production would add ~$30 for a second AZ + redundancy; QA stays single AZ.

---

## Risks + Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| DNS misconfiguration causes intermittent QA unreachability | Med | Use Route53 health checks; document apex DNS owner |
| EBS detach during EC2 instance refresh loses data | Med | EBS volume created separately, only attached after instance is up; lifecycle policy: never delete on instance termination |
| GitHub Actions OIDC IAM trust policy misconfigured | Med | Tested on a sandbox account first; explicit `sts:AssumeRoleWithWebIdentity` condition on the GH org+repo+branch |
| ALB cert expiry breaks QA | Low | ACM auto-renews if DNS validation record stays in Route53 |
| Cloud-agnostic constraint slips (someone adds RDS later) | Low | Lint script grepping for `aws_db_instance` / `aws_rds_cluster` in any infra script; PR template checkbox |

---

## Resolved (was: Open Questions for User) — 2026-05-30

1. **AWS account & access** — ✅ Account exists: **`449901518037`** (INNOARTHI PRIVATE LIMITED). IAM user `tnb-qong` has `AdministratorAccess`. Profile name: **`tnbqong`**. Account is **treated as production** per `../../../may26aws/CLAUDE.md` — every mutation requires same-turn approval + cost estimate.
2. **DNS ownership** — ✅ **Cloudflare** (NOT Route53). Apex zone `qongsystems.com` is on Cloudflare. Implication: ACM cert is still on AWS but validated via a CNAME the user adds to Cloudflare. ALB attached via Cloudflare CNAME with **orange-cloud OFF** (DNS-only) — proxying through Cloudflare would conflict with AWS-managed cert.
3. **GitHub Actions auth** — Decision deferred. Initial bootstrap uses local CLI + SSM. Wire OIDC after first successful manual deploy proves the topology works. Faster path to a live URL today.
4. **Region** — ✅ **`ap-south-1` (Mumbai)** — matches existing infra in the same account. Avoids cross-region SG/VPC complications.

---

## Implementation Order (estimated)

1. Answer open questions, set up AWS account if needed — 0.5 day
2. Create VPC bits + EC2 + EBS + ALB + ACM + DNS — 0.5 day
3. Bootstrap instance (docker, repo clone, env, first-run) — 0.25 day
4. Wire GitHub Actions deploy + secrets — 0.5 day
5. Smoke test + push spec-A changes — 0.25 day
6. Document + train team on QA usage — 0.25 day

**Total: ~2.25 days of focused work.**
