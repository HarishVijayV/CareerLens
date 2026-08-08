# Cloud & Kubernetes — Learning Plan

A staged plan to go from "runs on my laptop" to "runs in the cloud", using **this one
project** as the vehicle. Every stage produces something you can demo and explain.

The core idea: **learn one new thing at a time.** Kubernetes on a cloud cluster means
debugging Kubernetes *and* cloud IAM *and* networking simultaneously, and you can't tell
which one is failing. Learn Kubernetes locally, then move the *working* thing to cloud.

---

## Where you are now — Stage 2 is DONE

| Stage | Status |
|---|---|
| 1. Docker & Compose | ✅ 11 containers, one command |
| 2. **Kubernetes locally (kind)** | ✅ **14/14 pods, Ingress routing, self-healing verified** |
| 3. CI/CD to a registry | ✅ built; publish enabled on `main` |
| 4. Cloud VM + k3s | ← next |
| 5. Managed services | later |
| 6. Observability | later |

---

## The free-tier landscape (checked August 2026)

Cloud free tiers change, and one changed badly this year. Current reality:

| Provider | What's actually free | Verdict |
|---|---|---|
| **Oracle (OCI)** | **2 OCPU + 12 GB RAM ARM, forever** — halved from 4/24 in June 2026 | **Best for a permanent free host** |
| **GCP** | $300 / 90 days. GKE gives $74.40/mo credit — covers the *control plane only*, nodes still cost | Best for *learning managed* Kubernetes, short-term |
| **AWS** | 12-month t2.micro. **EKS control plane ≈ $73/month — not free** | Learn the vocabulary, don't host here |
| **Azure** | $200 / 30 days. AKS control plane free, **nodes cost** | Same as AWS |

⚠️ **Oracle warning:** Oracle halved the Always Free ARM allowance to 2 OCPU / 12 GB on
15 June 2026 with no announcement, and said instances exceeding the new limits would be
terminated from **18 August 2026**. Size your instance at or under 2 OCPU / 12 GB.

**Conclusion:** OCI for permanent free hosting; GCP's $300 credit for a few weeks of real
managed-Kubernetes experience; AWS only if a job description demands the names.

---

## Stage 3 — CI/CD to a registry *(mostly done)*

Already wired in `.github/workflows/ci.yml`:

```
push to main
  → lint + 33 tests          (gate: no build from failing code)
  → frontend typecheck+build (gate)
  → helm lint + template     (gate)
  → build 8 images in parallel
  → push to GHCR, tagged `latest` AND `sha-<commit>`
  → [deploy — disabled until you have a cluster]
```

**Why two tags:** `latest` is convenient, the SHA tag makes a deploy traceable to exact
source and a rollback just "redeploy the previous SHA".

**To do now:** after the first push to `main`, check the **Actions** tab, then look at
**Packages** on your GitHub profile — your images will be there, public and pullable.

---

## Stage 4 — A real cloud VM (this is the one to do next)

**Goal:** the app on a public IP, on hardware you don't own, restarting itself when it
dies.

1. **Sign up at Oracle Cloud** → https://cloud.oracle.com/ (card for verification, not
   charged for Always Free).
2. **Create an Ampere A1 instance**: Ubuntu 24.04, **2 OCPU / 12 GB** (do not exceed).
   Expect `Out of capacity` — ARM is in demand. Retry across days or pick another region.
3. **Open the ports.** OCI blocks everything by default, in *two* places, and forgetting
   the second is the classic first-day mistake:
   - the **Security List** on the subnet (cloud firewall), and
   - `iptables` **inside** the VM (Oracle images ship with rules pre-loaded)
4. **Install k3s** — a certified Kubernetes distribution, one command:
   ```bash
   curl -sfL https://get.k3s.io | sh -
   sudo cat /etc/rancher/k3s/k3s.yaml     # your kubeconfig
   ```
   Same `kubectl`, same manifests, same Helm chart. Real Kubernetes, ₹0/month.
5. **Deploy your existing chart** — nothing to rewrite:
   ```bash
   kubectl create secret generic careerlens-secrets --from-literal=...
   helm upgrade --install careerlens k8s/helm/careerlens \
     --set global.imageRegistry=ghcr.io/harishvijayv/careerlens \
     --set global.imagePullPolicy=Always \
     --set ingress.host=<your-domain-or-ip>
   ```
6. **Enable the deploy job** in CI (flip `if: false`), storing the kubeconfig as the
   `KUBE_CONFIG` secret. Now a push to `main` deploys itself.

**What you'll have learned:** VMs, SSH keys, cloud firewalls vs host firewalls, public
DNS, a real Kubernetes cluster, and automated deploys.

**Optional polish:** a free domain, then cert-manager + Let's Encrypt for real HTTPS.
Flip `ingress.tls.enabled=true` and set `COOKIE_SECURE=true`.

---

## Stage 5 — Managed services (use GCP's $300 credit)

Run the *same chart* on **GKE** for a couple of weeks. Point of the exercise: see what
"managed" actually buys you.

```bash
gcloud container clusters create-auto careerlens --region=asia-south1
helm upgrade --install careerlens k8s/helm/careerlens --set ingress.className=gce
```

Then swap in-cluster dependencies for managed ones — the chart already supports it:

```bash
--set postgres.enabled=false --set redis.enabled=false
# then point DATABASE_URL / REDIS_URL at Cloud SQL and Memorystore
```

**The lesson worth taking away:** running your own Postgres means owning backups,
failover, upgrades and point-in-time recovery. That's a full-time job a managed service
does better. Knowing *when to stop self-hosting* is a senior instinct.

⚠️ **Set a billing alert before you start**, and `gcloud container clusters delete` when
you're done. Credits expire; a forgotten cluster does not.

---

## Stage 6 — Observability (the thing most portfolios skip)

Right now you cannot answer *"is it healthy?"* without reading logs. That's the gap.

1. **Metrics:** `prometheus-fastapi-instrumentator` — one line per service gives request
   rate, latency and error rate for free.
2. **Prometheus + Grafana** via the kube-prometheus-stack Helm chart.
3. **A dashboard that answers real questions:** requests/sec, p95 latency, error rate,
   pod restarts, queue depth.
4. **One alert:** error rate > 5% for 5 minutes.

"How would you know if this broke in production?" is a standard interview question, and
almost nobody's portfolio has an answer.

---

## What's missing that you didn't ask about

Worth knowing these exist, in rough priority order:

| Gap | Why it matters | Effort |
|---|---|---|
| **Alembic migrations** | `create_all()` can't express a CHANGE to an existing table. First schema change on real data breaks. | Medium |
| **Postgres backups** | Self-hosted DB with no backup is one `kubectl delete pvc` from total loss. | Small |
| **Non-root containers** | Images run as root; `runAsNonRoot: true` is a standard security review item. | Small |
| **PodDisruptionBudget** | A node drain can currently evict every gateway replica at once. | Small |
| **NetworkPolicy** | Any pod can reach any pod. You already did this at the Docker layer for MCP — the k8s equivalent is missing. | Medium |
| **Secrets management** | k8s Secrets are base64-ENCODED, not encrypted. Sealed Secrets or External Secrets Operator. | Medium |
| **Load testing** | You have autoscaling config but have never proven it scales. `k6` for 15 minutes gives you a real number. | Small |
| **Terraform** | Clicking through a cloud console isn't reproducible. IaC is expected at most companies. | Large |

**If you do only three:** Alembic, backups, and load testing. The first two prevent data
loss; the third turns "I configured an HPA" into "I load-tested it and it scaled from 2
to 6 pods at 400 req/s."

---

## Free learning resources

| Topic | Resource |
|---|---|
| Kubernetes basics | https://kubernetes.io/docs/tutorials/kubernetes-basics/ |
| Interactive labs | https://killercoda.com/ (free, in-browser) |
| Helm | https://helm.sh/docs/chart_template_guide/ |
| CKA-level practice | https://github.com/dgkanatsios/CKAD-exercises |
| OCI free tier setup | https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm |
| k3s | https://docs.k3s.io/quick-start |
| Prometheus/Grafana | https://prometheus.io/docs/tutorials/getting_started/ |

---

## Suggested order

1. **This week** — push to `main`, watch CI build and publish images to GHCR
2. **Next** — Oracle account + ARM VM (start early; capacity errors are common)
3. **Then** — k3s + deploy the existing chart + enable CI deploy
4. **After** — pick two from the "missing" table (Alembic and backups)
5. **When you have a spare weekend** — GKE on the $300 credit, for the managed comparison
6. **Before interviews** — load test, so your autoscaling claim has a number behind it

Each stage is demonstrable on its own. Don't wait until the end to have something to show.
