# Automated deployment

Merging to `main` runs the tests, builds the Docker images, pushes them to the
GitHub Container Registry, and restarts the app on the VPS — with no manual
step. This page is the one-time setup, in order, followed by what to expect
afterwards.

Values used throughout as examples: domain `time.systemsandbox.work`, VPS user
`deploy`, app directory `/srv/timeme`, registry namespace
`ghcr.io/aimped`.

## How it fits together

```mermaid
flowchart TD
    M["Merge to main"] --> T1["test-backend<br/>pytest"]
    M --> T2["test-frontend<br/>tsc --noEmit"]
    T1 --> B["build-push<br/>2 images, tagged with the commit SHA"]
    T2 --> B
    B --> G[("ghcr.io/aimped<br/>timeme · timeme-backup")]
    B --> D["deploy<br/>ssh → /srv/timeme/deploy.sh SHA"]
    D --> P["docker compose pull + up -d"]
    G --> P
    P --> H{"container healthy<br/>within 90s?"}
    H -->|yes| OK["live"]
    H -->|no| RB["roll back to previous tag<br/>job fails red"]
```

Images are built **only** in CI. The VPS never compiles anything, so the
artifact the tests passed against is exactly the artifact that runs.

## Prerequisites

- A VPS with Docker Engine and the Compose plugin, plus Caddy running on the
  host as a systemd service.
- Push access to the GitHub repository.
- DNS for your domain managed somewhere you can add an A record.

---

## Step 1 — DNS

Add an A record for the app pointing at the VPS's IPv4 address:

| Type | Name | Content | Proxy |
|---|---|---|---|
| A | `time` | `<VPS IPv4>` | **DNS only** |

If your DNS is on Cloudflare, the record must be **grey cloud (DNS only)**, not
orange. Caddy provisions its own Let's Encrypt certificate, and a proxied record
means Cloudflare terminates TLS at its edge — the ACME challenge never reaches
Caddy and certificate issuance fails.

Verify before continuing:

```bash
host -t A time.systemsandbox.work
```

The answer must be your VPS's IP. If it returns a `188.114.*`, `104.*` or
`172.67.*` address, the record is still proxied.

## Step 2 — A deploy user on the VPS

SSH in as root or your admin user:

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo mkdir -p /home/deploy/.ssh && sudo chmod 700 /home/deploy/.ssh
sudo chown -R deploy:deploy /home/deploy/.ssh
```

Membership in `docker` is equivalent to root on the host — this account exists
only for deploys and should have no other use.

## Step 3 — The application directory

The VPS needs no source checkout. Four things live in `/srv/timeme`:

```
/srv/timeme/
├── docker-compose.yml   copied from the repo
├── deploy.sh            copied from the repo, executable
├── .env                 written by hand, never in git
└── backups/             owned by uid 10001
```

Create it:

```bash
sudo mkdir -p /srv/timeme
sudo chown deploy:deploy /srv/timeme
```

From your workstation, in a clone of the repo:

```bash
scp docker-compose.yml Caddyfile deploy@<VPS-IP>:/srv/timeme/
scp scripts/deploy.sh deploy@<VPS-IP>:/srv/timeme/deploy.sh
ssh deploy@<VPS-IP> chmod +x /srv/timeme/deploy.sh
```

`Caddyfile` is only staged here for Step 7 — Caddy reads it from `/etc/caddy/`.
Re-copy `docker-compose.yml` or `deploy.sh` whenever they change in the repo;
they are not updated by a deploy.

Then, on the VPS as `deploy`:

```bash
cd /srv/timeme

# The backup sidecar runs as uid 10001, matching the app.
mkdir -p backups && sudo chown 10001:10001 backups
```

Write `.env`. Take the template from `.env.example` in the repo and set a real
secret key:

```bash
cat > .env <<'EOF'
TIMEME_SECRET_KEY=REPLACE
TIMEME_TIMEZONE=Europe/Berlin
TIMEME_DEFAULT_NOMINAL_MINUTES=420
TIMEME_SESSION_HOURS=336
TIMEME_COOKIE_SECURE=true
TIMEME_BIND_PORT=8787
TIMEME_TAG=latest
BACKUP_AT=03:30
BACKUP_KEEP_DAYS=30
EOF

sed -i "s/^TIMEME_SECRET_KEY=.*/TIMEME_SECRET_KEY=$(openssl rand -hex 32)/" .env
chmod 600 .env
```

`TIMEME_TAG` is rewritten by `deploy.sh` on every deploy; `latest` is only the
bootstrap value. Changing `TIMEME_SECRET_KEY` later signs every user out.

## Step 4 — An SSH key for CI

On your workstation. A dedicated key, no passphrase — GitHub Actions cannot type
one:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/timeme_deploy -C "gh-actions-timeme" -N ""
```

Install the public half on the VPS:

```bash
ssh-copy-id -i ~/.ssh/timeme_deploy.pub deploy@<VPS-IP>
```

Confirm it works, and that the deploy user can drive Docker:

```bash
ssh -i ~/.ssh/timeme_deploy deploy@<VPS-IP> 'docker ps && echo OK'
```

## Step 5 — Let the VPS pull from the registry

The VPS has no GitHub credentials of its own. Create a **classic personal access
token** with only the `read:packages` scope at
<https://github.com/settings/tokens>, then, on the VPS as `deploy`:

```bash
echo '<TOKEN>' | docker login ghcr.io -u AIMPED --password-stdin
```

This is stored in `~/.docker/config.json` and survives reboots. Doing it now
means the very first automated deploy works end to end.

Alternatively, after the first CI run has created the packages, set both to
public under **Profile → Packages → timeme → Package settings → Change
visibility**, and no login is needed. The images contain no secrets — every
sensitive value arrives from `.env` at runtime.

## Step 6 — GitHub repository secrets

Go to **`https://github.com/AIMPED/timeMe/settings/secrets/actions`**.

These are *repository* settings — the Settings tab in the repository's own top
bar, not the account settings behind your avatar. Use the **Secrets** tab, not
Variables; variables are readable in logs.

Add three repository secrets:

| Name | Value |
|---|---|
| `VPS_HOST` | The VPS's raw IPv4 address |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | Entire contents of `~/.ssh/timeme_deploy` (the file *without* `.pub`) |

`VPS_HOST` must be the IP, not your domain — if the domain is proxied, SSH to
port 22 will never reach the VPS. A **DNS only** subdomain such as
`vps.systemsandbox.work` also works.

Paste the private key complete with its `-----BEGIN OPENSSH PRIVATE KEY-----`
and `-----END …-----` lines and the trailing newline. A truncated key fails with
an unhelpful handshake error.

While in Settings, check **Actions → General → Workflow permissions** is set to
**Read and write permissions**, so the build job may push packages.

## Step 7 — Caddy

Install the `Caddyfile` staged in Step 3, with your own domain substituted:

```bash
sudo cp /srv/timeme/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/time\.example\.com/time.systemsandbox.work/' /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy fetches the certificate on the first request. The app publishes only to
`127.0.0.1:8787`, so Caddy is the sole route in — no firewall rule is needed for
the app itself, only ports 80, 443 and 22.

## Step 8 — First deploy

Merge the workflow to `main`. Watch it under the repository's **Actions** tab:
four jobs, roughly two minutes end to end.

When it goes green, create the first administrator on the VPS:

```bash
cd /srv/timeme
docker compose exec app python -m app.cli create-user alice --admin --name "Alice"
```

Then open `https://time.systemsandbox.work` and sign in.

---

## Verifying a deployment

```bash
cd /srv/timeme

grep TIMEME_TAG .env                 # which commit is live
docker compose ps                    # both containers up, app healthy
docker compose logs --tail 30 app
curl -s localhost:8787/api/health    # from the VPS itself
docker compose logs backup | tail -5 # the start-up backup ran
```

The tag in `.env` is the full commit SHA, so it maps directly back to a commit
on `main`.

## Rolling back

`deploy.sh` rolls back automatically if the new container fails to report
healthy within 90 seconds — a red `deploy` job means the previous version is
still serving.

To go back deliberately, run the same script with an older commit SHA:

```bash
/srv/timeme/deploy.sh 89aeeef0c1b2c3d4e5f6...
```

Any SHA still present in the registry works. Since the data lives in the
`timeme-data` volume and is untouched by a deploy, this only changes code.

## What happens on every merge from now on

| Stage | Duration | Notes |
|---|---|---|
| `test-backend` | ~20s | `pytest` against a temp SQLite file |
| `test-frontend` | ~40s | `tsc --noEmit` |
| `build-push` | 40s–4min | Two images; layer-cached between runs |
| `deploy` | ~20s | Pull, restart, health gate |

Pull requests run the two test jobs only — nothing is built or deployed until
the merge. A failing test never produces an image, and a failed push never
reaches the VPS.

There is a brief interruption of a second or two while the container restarts,
during which Caddy returns an error to anyone mid-request.

## Known limitation: schema changes

There is no migration framework. The schema is created on start-up, so a
release that only *adds* to the model on a fresh database is fine, but a change
to an existing table is not applied to the SQLite file already in the volume.
The health gate catches a release that crashes on boot; it cannot catch one that
starts happily against a stale schema.

Until Alembic or similar is in place, treat any change to `backend/app/models.py`
as a manual operation: take a backup, apply the change deliberately, then deploy.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `deploy` job: `ssh: handshake failed` | `VPS_SSH_KEY` truncated or missing header lines; or the public half was never added to `authorized_keys`. |
| `deploy` job: connection timeout | `VPS_HOST` is a proxied hostname instead of the IP, or port 22 is firewalled. |
| `build-push`: `denied: permission_denied` | Workflow permissions are read-only (Step 6). |
| On the VPS: `denied` / `unauthorized` on pull | The `docker login ghcr.io` in Step 5 was skipped, or the token lacks `read:packages`. |
| `exec format error` in the app logs | Image architecture mismatch. Set `platforms: linux/arm64` in `.github/workflows/ci-deploy.yml` for an ARM VPS. |
| Site unreachable, Caddy logs show ACME failures | The DNS record is proxied. Set it to DNS only (Step 1). |
| Browser cannot log in, cookie rejected | `TIMEME_COOKIE_SECURE=true` over plain HTTP. Use HTTPS, which Caddy provides. |
| `deploy.sh` reports unhealthy and rolls back | Read `docker compose logs app`. Usually a missing variable in `.env` or a schema change against an existing database. |
| Backup logs show permission errors | `backups/` is not owned by uid 10001 (Step 3). |
