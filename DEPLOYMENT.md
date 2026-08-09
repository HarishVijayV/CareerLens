# DEPLOYMENT — putting CareerLens on the internet, step by step

**Who this is for.** Someone who has never deployed this before. Every command is written
out. Nothing is assumed. If a step needs a value from an earlier step, it says so.

**What you will end up with.** A public HTTPS URL anyone can open, running all nine
containers, with Google login working and your data safe across restarts.

**Time.** About 2 hours the first time. Most of it is waiting for things to build, and
about 30 minutes is the fiddly part: URLs, redirects and cookies.

---

## Table of contents

- [0. Understand the shape before you start](#0-understand-the-shape-before-you-start)
- [1. What you need before you begin](#1-what-you-need-before-you-begin)
- [PATH A — one server with Docker Compose (start here)](#path-a--one-server-with-docker-compose-start-here)
  - [A1. Create the server](#a1-create-the-server)
  - [A2. Open the right ports only](#a2-open-the-right-ports-only)
  - [A3. Log in to the server](#a3-log-in-to-the-server)
  - [A4. Install Docker](#a4-install-docker)
  - [A5. Get the code](#a5-get-the-code)
  - [A6. Write the .env file](#a6-write-the-env-file)
  - [A7. Start it](#a7-start-it)
  - [A8. Put a domain and HTTPS in front](#a8-put-a-domain-and-https-in-front)
- [2. THE FIDDLY PART — URLs, redirects, CORS, cookies](#2-the-fiddly-part--urls-redirects-cors-cookies)
- [3. Load the data](#3-load-the-data)
- [4. How code gets from your laptop to the server](#4-how-code-gets-from-your-laptop-to-the-server)
- [PATH B — Kubernetes with Helm](#path-b--kubernetes-with-helm)
- [5. When something breaks](#5-when-something-breaks)
- [6. Cost, and what to do when free credit ends](#6-cost-and-what-to-do-when-free-credit-ends)

---

## 0. Understand the shape before you start

Five minutes here saves an hour later.

**On your laptop today**, everything runs in Docker and talks over `localhost`. The
browser reaches the gateway at `http://localhost:8000`, and the gateway reaches the other
services by their container names (`auth-service:8000`).

**On a server**, two things change and everything else stays the same:

1. `localhost` becomes a real address, and it must be **HTTPS** — Google refuses to
   send a login back to a plain `http://` address that isn't localhost.
2. Anything you told a *third party* about your address (Google's redirect URL) has to
   be told again with the new address.

That is genuinely most of the work. The containers do not change at all.

```
   YOUR LAPTOP                         THE SERVER
   browser -> localhost:3000           browser -> https://yourdomain.com
           -> localhost:8000/api               -> https://yourdomain.com/api
                                                        |
                                                    nginx  (adds HTTPS)
                                                        |
                                       frontend:3000 and gateway:8000
                                                        |
                                       auth / jobs / agent / worker / mcp
                                                        |
                                              postgres + redis
```

---

## 1. What you need before you begin

Collect these first. Stopping halfway to hunt for a key is how mistakes happen.

| What | Where to get it | Needed for |
|---|---|---|
| A cloud account | Azure, Oracle, AWS — any Linux VM | the server |
| A domain name | Namecheap ~£8/yr, or a free DuckDNS subdomain | HTTPS |
| `FIREWORKS_API_KEY` | fireworks.ai | the AI assistant |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | developer.adzuna.com (free) | fetching real jobs |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Google Cloud Console | Gmail tracking (optional) |

**Server size.** 2 vCPU and 4 GB RAM. The stack uses about 1.5 GB, and you want headroom.

> **Do not use a 1 GB server.** Azure's free B1S is 1 GB and the stack will run out of
> memory. On Azure use **B2s**; on Oracle use the Always Free **ARM** instance, which gives
> you 4 cores and 24 GB for nothing, forever.

---

## PATH A — one server with Docker Compose (start here)

Do this first even if you want Kubernetes. It proves the app works on a real server, and
it is far easier to debug. Kubernetes is Path B.

### A1. Create the server

**On Azure:**

1. Go to <https://portal.azure.com> and sign in.
2. In the search bar at the top type **Virtual machines**, click it.
3. Click **Create** → **Azure virtual machine**.
4. Fill in:
   - **Resource group** → *Create new* → name it `careerlens`
   - **Virtual machine name** → `careerlens-vm`
   - **Region** → the one nearest you (`Central India`, `East US`, …)
   - **Image** → **Ubuntu Server 22.04 LTS**
   - **Size** → click *See all sizes*, choose **B2s** (2 vcpus, 4 GiB)
   - **Authentication type** → **SSH public key**
   - **Username** → `azureuser`
   - **SSH public key source** → *Generate new key pair*
   - **Public inbound ports** → **None** (we open them properly in A2)
5. Click **Review + create**, then **Create**.
6. A box appears: **Download private key and create resource**. Click it. A file called
   `careerlens-vm_key.pem` downloads.

> **Keep that .pem file.** It is the only way into your server. Lose it and you start over.

7. Wait ~2 minutes. Click **Go to resource**. Copy the **Public IP address** — call this
   `<SERVER_IP>` from now on.

**On Oracle Cloud:** create a **Compute Instance**, image *Canonical Ubuntu 22.04*, shape
**VM.Standard.A1.Flex** with 4 OCPU / 24 GB (Always Free). Download the private key when
offered. The rest of this guide is identical.

### A2. Open the right ports only

Your server must accept web traffic and SSH. Nothing else.

**On Azure:**

1. On your VM's page, in the left menu click **Networking** → **Network settings**.
2. Click **Create port rule** → **Inbound port rule**, and add these three, one at a time:

| Destination port | Protocol | Priority | Name | Why |
|---|---|---|---|---|
| 22 | TCP | 300 | SSH | so you can log in |
| 80 | TCP | 310 | HTTP | so Let's Encrypt can verify your domain |
| 443 | TCP | 320 | HTTPS | the actual site |

> **Do NOT open 3000, 8000–8003, or 5432.** Those are internal. Opening 5432 puts your
> database on the public internet, and automated scanners find it within hours.

**On Oracle:** the same thing lives under **Networking → Virtual Cloud Networks → your
VCN → Security Lists → Default Security List → Add Ingress Rules**.

### A3. Log in to the server

Open PowerShell **on your laptop**, in the folder where the `.pem` file downloaded:

```powershell
# Windows only: a key file the whole machine can read is refused by SSH.
icacls careerlens-vm_key.pem /inheritance:r
icacls careerlens-vm_key.pem /grant:r "$($env:USERNAME):(R)"

ssh -i careerlens-vm_key.pem azureuser@<SERVER_IP>
```

Type `yes` when it asks about authenticity. You are now on the server — every command from
here until Path B runs there.

### A4. Install Docker

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh

# Lets you run docker without typing sudo every time.
sudo usermod -aG docker $USER
```

**Now log out and back in** — group membership only applies to a new session:

```bash
exit
ssh -i careerlens-vm_key.pem azureuser@<SERVER_IP>
docker --version        # should print a version, with no permission error
```

### A5. Get the code

```bash
git clone https://github.com/HarishVijayV/CareerLens.git
cd CareerLens
```

### A6. Write the .env file

This is the step people rush and then spend an hour debugging. Do it slowly.

```bash
cd infra
cp .env.example .env
nano .env
```

`nano` is a text editor. Arrow keys to move, type to edit, **Ctrl+O** then **Enter** to
save, **Ctrl+X** to exit.

First, generate two secrets. Run this **in a second terminal on your laptop** (or on the
server in another SSH session) and copy the output:

```bash
openssl rand -hex 32     # use for JWT_SECRET_KEY
openssl rand -hex 32     # run again, use for TOKEN_ENCRYPTION_KEY
```

Now fill in `.env`. Replace `yourdomain.com` with your real domain:

```bash
# ---- database ----
POSTGRES_USER=careerlens
POSTGRES_PASSWORD=<a long random password you invent>
POSTGRES_DB=careerlens

# ---- secrets (from openssl above — NOT the example values) ----
JWT_SECRET_KEY=<first openssl output>
TOKEN_ENCRYPTION_KEY=<second openssl output>

# ---- THE PART THAT CHANGES FOR A SERVER ----
FRONTEND_URL=https://yourdomain.com
GOOGLE_REDIRECT_URI=https://yourdomain.com/api/auth/google/callback
COOKIE_SECURE=true
COOKIE_DOMAIN=yourdomain.com

# ---- AI ----
LLM_PROVIDER=fireworks
FIREWORKS_API_KEY=<your key>
FIREWORKS_MODEL=accounts/fireworks/models/deepseek-v4-flash

# ---- real job data ----
ADZUNA_APP_ID=<your id>
ADZUNA_APP_KEY=<your key>

# ---- Google login (leave blank to skip Gmail tracking) ----
GOOGLE_CLIENT_ID=<your id>
GOOGLE_CLIENT_SECRET=<your secret>
```

**Why each of the four "server" lines matters:**

| Line | What breaks if it is wrong |
|---|---|
| `FRONTEND_URL` | The gateway's CORS uses it. Wrong value → every API call is blocked by the browser and the site looks empty. |
| `GOOGLE_REDIRECT_URI` | Google sends you back here after login. Wrong value → `redirect_uri_mismatch`. |
| `COOKIE_SECURE=true` | Over HTTPS a cookie without `Secure` may be dropped → you log in and are instantly logged out. |
| `COOKIE_DOMAIN` | Which site the cookie belongs to. |

> **Never commit `.env`.** It is already in `.gitignore`. It holds every key you own.

One more, and it is the one that catches everybody:

```bash
nano docker-compose.yml
```

Find `NEXT_PUBLIC_API_BASE_URL` under `frontend:` and change it:

```yaml
      NEXT_PUBLIC_API_BASE_URL: https://yourdomain.com/api
```

**Why this one is special.** Anything starting `NEXT_PUBLIC_` is baked into the JavaScript
**at build time**, not read when the app runs. So changing it later means rebuilding the
frontend image — editing `.env` alone does nothing. If the site loads but every request
goes to `localhost:8000`, this is why.

### A7. Start it

```bash
docker compose up -d --build
```

First build takes 5–10 minutes. Then check:

```bash
docker compose ps          # all nine should say "running"
curl localhost:3000        # should print HTML
curl localhost:8000/health # should print {"status":"ok"}
```

If a container is restarting, jump to [section 5](#5-when-something-breaks).

### A8. Put a domain and HTTPS in front

Right now the site works only from inside the server. Two things fix that: pointing a
domain at your IP, and putting nginx in front to handle HTTPS.

**First, point the domain at your server.** In your domain registrar's DNS settings add:

| Type | Name | Value |
|---|---|---|
| A | `@` | `<SERVER_IP>` |
| A | `www` | `<SERVER_IP>` |

Wait 5–30 minutes, then check from your laptop:

```bash
nslookup yourdomain.com     # should show <SERVER_IP>
```

**Then install nginx and a certificate**, on the server:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo nano /etc/nginx/sites-available/careerlens
```

Paste this, replacing `yourdomain.com`:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    # Anything under /api goes to the gateway. Everything else is the website.
    # This is what makes the whole app one origin — which is why cookies work
    # without any cross-site configuration.
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # The assistant can take 90+ seconds: it is a chain of LLM calls.
        # nginx's 60s default would cut it off and show a 504.
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Save (Ctrl+O, Enter, Ctrl+X), then:

```bash
sudo ln -s /etc/nginx/sites-available/careerlens /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t          # must say "syntax is ok"
sudo systemctl reload nginx

# Free certificate. Answer the email prompt, agree to terms,
# and choose "redirect HTTP to HTTPS" when asked.
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Open `https://yourdomain.com` in a browser. You should see the site with a padlock.

Certbot renews automatically — nothing more to do.

---

## 2. THE FIDDLY PART — URLs, redirects, CORS, cookies

Everything on this list must point at your new address. Miss one and something breaks in
a way that looks unrelated. Work through it in order.

### 2.1 Google OAuth — in Google Cloud Console

Google only sends users back to addresses you have registered in advance.

1. Go to <https://console.cloud.google.com>
2. Top-left project dropdown → select the project holding your OAuth client
3. Left menu → **APIs & Services** → **Credentials**
4. Under *OAuth 2.0 Client IDs*, click your Web client
5. Under **Authorised JavaScript origins** click *ADD URI*:
   ```
   https://yourdomain.com
   ```
6. Under **Authorised redirect URIs** click *ADD URI*:
   ```
   https://yourdomain.com/api/auth/google/callback
   ```
7. Click **SAVE**

> Keep the localhost entries as well. Then Gmail login still works on your laptop.
> Google allows many URIs per client.

**This must match `GOOGLE_REDIRECT_URI` in `.env` character for character** — including
`https` vs `http`, and no trailing slash. `redirect_uri_mismatch` means these two strings
differ somewhere.

Also, while you are here: **APIs & Services → OAuth consent screen**. If it says *Testing*,
add your Gmail address under **Test users**, or login will be refused.

### 2.2 CORS — already handled, but know why

A browser blocks a page on one address from calling an API on another. The gateway allows
exactly one origin, read from `FRONTEND_URL`:

```python
allow_origins=[settings.frontend_origin]      # services/gateway/app/main.py
```

Set `FRONTEND_URL=https://yourdomain.com` and it is correct. **Do not** set it to `*` —
that disables the protection, and with cookie auth the browser refuses it anyway.

Because nginx serves the site and the API on the *same* domain, CORS barely comes into
play at all. That is a real reason to prefer this layout over hosting the frontend
somewhere separate.

### 2.3 Cookies

| Setting | Laptop | Server | Why |
|---|---|---|---|
| `COOKIE_SECURE` | `false` | **`true`** | A `Secure` cookie is only sent over HTTPS. Without it on a real site, tokens travel in the clear. |
| `COOKIE_DOMAIN` | *(empty)* | `yourdomain.com` | Which site owns the cookie. |

If you can log in but are immediately logged out again, it is nearly always one of these
two, or `NEXT_PUBLIC_API_BASE_URL` still pointing at localhost.

### 2.4 The complete checklist

Print this. Tick each one.

- [ ] `.env` → `FRONTEND_URL=https://yourdomain.com`
- [ ] `.env` → `GOOGLE_REDIRECT_URI=https://yourdomain.com/api/auth/google/callback`
- [ ] `.env` → `COOKIE_SECURE=true`
- [ ] `.env` → `COOKIE_DOMAIN=yourdomain.com`
- [ ] `.env` → real `JWT_SECRET_KEY` and `TOKEN_ENCRYPTION_KEY`, not the examples
- [ ] `.env` → a strong `POSTGRES_PASSWORD`
- [ ] `docker-compose.yml` → `NEXT_PUBLIC_API_BASE_URL: https://yourdomain.com/api`
- [ ] Google Console → JavaScript origin added
- [ ] Google Console → redirect URI added
- [ ] Google Console → your email under Test users (if consent screen is *Testing*)
- [ ] Cloud firewall → 22, 80, 443 open; **5432 and 8000-8003 closed**
- [ ] DNS A record → points at `<SERVER_IP>`
- [ ] `certbot` run and the site shows a padlock
- [ ] `.env` is NOT in git (`git status` should not list it)

---

## 3. Load the data

A fresh server has an empty database, so the job board will be empty.

**The pipeline needs Java and Spark, and wants a lot of memory in bursts.** Do not install
it on a small server. Run it on your laptop and copy the results up.

**On your laptop:**

```bash
cd pipeline
python run_pipeline.py            # ~7 minutes

# Dump the finished warehouse
pg_dump -h localhost -U careerlens -d careerlens \
        -n analytics -n raw -f warehouse.sql
```

**Copy it to the server and load it:**

```bash
scp -i careerlens-vm_key.pem warehouse.sql azureuser@<SERVER_IP>:~/
ssh -i careerlens-vm_key.pem azureuser@<SERVER_IP>

docker cp warehouse.sql infra-postgres-1:/tmp/
docker exec -i infra-postgres-1 psql -U careerlens -d careerlens -f /tmp/warehouse.sql
```

Refresh the site — the jobs are there.

Repeat whenever you want fresh postings. Once a week is plenty; Adzuna's free quota is
daily and postings do not change by the minute.

---

### 3.1 Making the pipeline run itself

On a laptop a schedule is not really a schedule: Airflow is a container, so it stops when
the machine sleeps, and `catchup=False` means missed days are simply missed. A server that
never sleeps is the first place a daily run actually holds — which is a better reason to
host this than the public URL.

On the server:

```bash
cd ~/CareerLens/infra
docker compose --profile bigdata up -d                     # Airflow + Kafka (~1.2GB)
docker compose exec airflow-scheduler airflow dags unpause job_pipeline
```

Two cautions before you do:

* **RAM.** The bigdata profile adds ~1.2GB. On a 4GB VM running the app as well, that is
  tight. Check with `docker stats` before leaving it running.
* **Spark.** The DAG's ETL step wants Java and burst memory. On a small VM, either keep
  running the pipeline on your laptop and copying the dump up (section 3), or give the DAG
  only the ingest and dbt steps and leave Spark local.

Airflow's UI is on **:8080**, which you should NOT open to the internet. Reach it through
an SSH tunnel instead of a firewall rule:

```bash
ssh -i careerlens-vm_key.pem -L 8080:localhost:8080 azureuser@<SERVER_IP>
```

Then open <http://localhost:8080> on your own machine. The tunnel closes with the SSH
session, so nothing is left exposed.

## 4. How code gets from your laptop to the server

You have two ways. Start with the simple one.

### The simple way — pull and rebuild

```bash
ssh -i careerlens-vm_key.pem azureuser@<SERVER_IP>
cd CareerLens
git pull
cd infra
docker compose up -d --build
```

That is it. Builds on the server, takes a few minutes.

### The proper way — CI builds the images, the server just pulls

This already works. Every push to `main` triggers `.github/workflows/ci.yml`, which:

1. **Lints and tests** the Python
2. **Type-checks and builds** the frontend
3. **Validates** the Helm chart
4. **Builds and pushes eight images** to **GHCR** (GitHub Container Registry) —
   only if all three gates passed, and only from `main`

```
   git push
       |
   GitHub Actions
       |
   [test] [frontend] [helm]      <- all must pass
       |
   [images] -> ghcr.io/harishvijayv/careerlens/<service>:latest
       |
   your server: docker compose pull && up -d
```

> **Why GHCR and not Azure Container Registry?** GHCR is free for public images and needs
> **zero setup** — `secrets.GITHUB_TOKEN` is provided by GitHub automatically. ACR costs
> money and requires creating a service principal. There is nothing to gain here.
>
> If you *must* use ACR (e.g. an assignment requires it): create the registry, run
> `az acr credential show`, add `ACR_USERNAME` and `ACR_PASSWORD` as GitHub repository
> secrets, and change the `REGISTRY` variable at the top of `ci.yml`. Nothing else changes.

**To pull prebuilt images instead of building on the server**, create
`infra/docker-compose.prod.yml`:

```yaml
services:
  gateway:
    image: ghcr.io/harishvijayv/careerlens/gateway:latest
    build: !reset null          # ignore the build section, just pull
  auth-service:
    image: ghcr.io/harishvijayv/careerlens/auth-service:latest
    build: !reset null
  jobs-service:
    image: ghcr.io/harishvijayv/careerlens/jobs-service:latest
    build: !reset null
  agent-service:
    image: ghcr.io/harishvijayv/careerlens/agent-service:latest
    build: !reset null
  worker-service:
    image: ghcr.io/harishvijayv/careerlens/worker-service:latest
    build: !reset null
  mcp-server:
    image: ghcr.io/harishvijayv/careerlens/mcp-server:latest
    build: !reset null
  frontend:
    image: ghcr.io/harishvijayv/careerlens/frontend:latest
    build: !reset null
```

Then deploying is:

```bash
cd ~/CareerLens && git pull
cd infra
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Seconds instead of minutes, and the server never compiles anything.

> **Caveat on the frontend image.** `NEXT_PUBLIC_API_BASE_URL` is baked in at build time,
> so a CI-built frontend carries whatever CI had. Either add it as a build argument in the
> workflow, or keep building the frontend on the server while pulling the rest.

---

## PATH B — Kubernetes with Helm

Only do this after Path A works. Kubernetes solves problems Compose does not have —
rolling deploys, self-healing, autoscaling — and adds real complexity.

**Be honest about the cost.** Managed Kubernetes (AKS/OKE/EKS) needs 2–3 nodes to be
worth anything, which is well beyond a free tier. Options:

- **k3s** — a full Kubernetes that runs on your single 4 GB VM. Free. Best choice here.
- **AKS** — real managed Kubernetes, but the node pool is not free.
- **kind on your laptop** — costs nothing, proves the manifests work, nobody else can reach it.

### B1. Install k3s on the server

```bash
curl -sfL https://get.k3s.io | sh -
sudo chmod 644 /etc/rancher/k3s/k3s.yaml
echo 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml' >> ~/.bashrc
source ~/.bashrc

kubectl get nodes      # one node, status Ready
```

### B2. Install Helm

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

### B3. Let Kubernetes pull your images

GHCR images from a private repo need credentials. If your repo is public, skip this.

```bash
kubectl create secret docker-registry ghcr-creds \
  --docker-server=ghcr.io \
  --docker-username=HarishVijayV \
  --docker-password=<a GitHub personal access token with read:packages> \
  --docker-email=you@example.com
```

### B4. Put the secrets in Kubernetes

Kubernetes does not read your `.env`. Create a Secret from it:

```bash
cd ~/CareerLens
kubectl create secret generic careerlens-secrets --from-env-file=infra/.env
```

### B5. Deploy

```bash
# See exactly what will be created, before creating anything.
helm template careerlens k8s/helm/careerlens \
  --set global.imageTag=latest \
  --set global.imagePullPolicy=Always | less

helm install careerlens k8s/helm/careerlens \
  --set global.imageTag=latest \
  --set global.imagePullPolicy=Always
```

> `imagePullPolicy` **must** be `Always` in the cloud. The default is `IfNotPresent`,
> which is right for `kind` (images are loaded straight into the node and there is no
> registry copy) and wrong on a server, where it would keep running a stale image.

Watch it come up:

```bash
kubectl get pods -w        # Ctrl+C when everything is Running
kubectl get svc
kubectl get ingress
```

### B6. Updating

```bash
helm upgrade careerlens k8s/helm/careerlens --set global.imageTag=latest
kubectl rollout status deployment/careerlens-gateway

# If the new version is bad:
helm rollback careerlens
```

That rollback is the whole reason for Helm. With raw YAML you would be hunting for the
previous manifests.

---

## 5. When something breaks

Work top to bottom. Each command narrows it down.

```bash
docker compose ps                      # what state is everything in?
docker compose logs -f auth-service    # what is that container saying?
docker compose logs --tail=50 gateway
docker stats --no-stream               # is something eating all the RAM?
df -h                                  # is the disk full?
```

| What you see | What it means | Fix |
|---|---|---|
| Site loads, no data, browser console shows CORS | `FRONTEND_URL` wrong | Fix `.env`, `docker compose up -d` |
| Every API call goes to `localhost:8000` | `NEXT_PUBLIC_API_BASE_URL` still local | Fix compose, **rebuild the frontend** |
| `redirect_uri_mismatch` from Google | Console URI ≠ `.env` URI | Make them identical, character for character |
| Log in, instantly logged out | `COOKIE_SECURE`/`COOKIE_DOMAIN` | Set both correctly |
| A container restarts forever | Usually out of memory | `docker stats`; use a bigger VM |
| 502 from nginx | The container behind it is down | `docker compose ps` |
| 504 after ~60s on the assistant | nginx timeout too low | `proxy_read_timeout 300s` (A8) |
| `no space left on device` from Postgres | Almost never the disk — it is `/dev/shm` | `shm_size: 256mb` (already set) |
| Jobs page empty | No data loaded | Section 3 |
| Assistant says "check LLM_PROVIDER" | Bad or missing API key | Check `FIREWORKS_API_KEY` |
| Changed code, nothing changed | Stale image or anonymous volume | `docker compose up -d --build --force-recreate --renew-anon-volumes` |

**The single most useful habit:** read the logs of the specific container that is
misbehaving. The browser's error is usually three layers away from the cause.

---

## 6. Cost, and what to do when free credit ends

| Provider | Free | Then what |
|---|---|---|
| **Azure** | $200 credit, **30 days from signup** | ~$30/month for a B2s |
| **Oracle** | 4 ARM cores, 24 GB, **no expiry** | still free |
| **AWS** | t2.micro 1 GB, 12 months | too small for this |

**Azure's credit expires on a calendar, not on usage.** Leaving the VM switched off does
not save it. Day 31 it is gone whether you used it or not.

**Practical plan:** deploy on Azure while you are interviewing, then move to Oracle before
day 30. The second deploy takes about an hour because it is the same Docker Compose — only
sections A1, A2 and A8 differ, and A8 only in where you click.

**Always stop the meter when you finish:**

```bash
# Azure — deallocate, otherwise you keep being charged for the VM
az vm deallocate --resource-group careerlens --name careerlens-vm
```

Deallocating stops compute charges. The disk still costs a little, and a *static* public
IP still costs. There is no way to keep a VM truly free on Azure.

> **Oracle caveat:** Oracle reclaims idle Always Free compute. Leave the stack running —
> it costs nothing — rather than shutting it down for weeks.

---

## What to say about this in an interview

> "It runs as nine containers behind an nginx reverse proxy that terminates TLS. CI runs
> lint, tests, a typecheck and a Helm lint, and only then builds and pushes eight images
> to GHCR — so nothing that failed a gate can be deployed. Deployment is a pull and a
> restart. The interesting part was not Docker; it was that going from localhost to a real
> domain means updating four things that live outside the code: the OAuth redirect
> registered with Google, the CORS origin, the cookie flags, and a build-time environment
> variable that is baked into the frontend bundle rather than read at runtime."

That last sentence is the one that sounds like someone who has actually deployed something.
