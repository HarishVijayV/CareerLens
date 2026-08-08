# Kubernetes — Running CareerLens on a Cluster

Verified working: **14/14 pods**, Ingress routing to frontend and API, signup completing
end-to-end, and self-healing confirmed by killing a pod mid-request.

---

## Run it yourself

```bash
# 1. cluster (3 nodes: 1 control-plane, 2 workers)
kind create cluster --config k8s/kind-config.yaml

# 2. ingress controller, pinned to the node that has the host port mappings
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl patch deployment ingress-nginx-controller -n ingress-nginx --type=strategic -p '{
  "spec":{"template":{"spec":{
    "nodeSelector":{"ingress-ready":"true","kubernetes.io/os":"linux"},
    "tolerations":[{"key":"node-role.kubernetes.io/control-plane","operator":"Equal","effect":"NoSchedule"}]
  }}}}'
kubectl wait --for=condition=ready pod -n ingress-nginx -l app.kubernetes.io/component=controller --timeout=180s

# 3. build + load images (kind can't pull from a local daemon)
for s in gateway auth-service jobs-service agent-service worker-service notification-service mcp-server; do
  docker build -t ghcr.io/harishvijayv/careerlens/$s:latest services/$s
  kind load docker-image ghcr.io/harishvijayv/careerlens/$s:latest --name careerlens
done
docker build -f frontend/Dockerfile -t ghcr.io/harishvijayv/careerlens/frontend:latest frontend
kind load docker-image ghcr.io/harishvijayv/careerlens/frontend:latest --name careerlens

# 4. secrets — created out of band, NEVER in values.yaml
kubectl create secret generic careerlens-secrets \
  --from-literal=POSTGRES_PASSWORD=change_me \
  --from-literal=JWT_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=TOKEN_ENCRYPTION_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=FIREWORKS_API_KEY=... \
  --from-literal=ADZUNA_APP_ID= --from-literal=ADZUNA_APP_KEY= \
  --from-literal=GOOGLE_CLIENT_ID= --from-literal=GOOGLE_CLIENT_SECRET= \
  --from-literal=GEMINI_API_KEY= --from-literal=OPENAI_API_KEY= --from-literal=ANTHROPIC_API_KEY=

# 5. deploy
helm install careerlens k8s/helm/careerlens
kubectl get pods -w
```

Then, with `careerlens.local` pointing at `127.0.0.1` in your hosts file:
**http://careerlens.local:8080** — or test directly:

```bash
curl -H "Host: careerlens.local" http://localhost:8080/
curl -H "Host: careerlens.local" http://localhost:8080/api/auth/me     # 401 = working
```

Teardown: `kind delete cluster --name careerlens`

---

## What's in the chart

| Resource | Count | Why |
|---|---|---|
| Deployment | 8 | stateless services + Celery worker |
| Service | 9 | stable in-cluster DNS names |
| StatefulSet | 2 | Postgres, Redis — need stable identity + their own volume |
| Ingress | 1 | the single public entrypoint |
| ConfigMap | 1 | non-secret config |
| HPA | 0–2 | opt-in; needs metrics-server |

---

## The decisions worth being able to explain

**One template, not eight files.** `templates/services.yaml` loops over `.Values.services`.
The differences between services are *data* (name, port, replicas, resources), so they
live in `values.yaml`. Eight copies means a fix applied seven times and forgotten once.

**Three probes, three different questions.** Conflating them is the classic mistake:

| Probe | Question | On failure |
|---|---|---|
| `startupProbe` | Has it finished booting? | gates the other two, so slow starts aren't killed |
| `readinessProbe` | Should it get traffic *now*? | removed from the Service — **not** restarted |
| `livenessProbe` | Is it wedged? | **restarted** |

An aggressive liveness probe is actively harmful: it restarts healthy-but-slow pods and
turns a load spike into an outage.

**StatefulSet for data.** A Deployment treats pods as interchangeable and would hand a
restarted database a different volume. A StatefulSet keeps the PVC attached to `-0`.

**`maxUnavailable: 0`.** New pods must be Ready before old ones go. A broken image fails
to roll out rather than taking the service down.

**Config checksum annotation.** Without it, a `helm upgrade` that only changes the
ConfigMap leaves running pods on stale env vars — "I changed it and nothing happened".

**Secrets aren't in `values.yaml`.** That file is committed. Note also that a Kubernetes
Secret is base64-**encoded**, not encrypted; encryption at rest is a separate cluster
setting.

---

## Self-healing, demonstrated

```bash
kubectl delete pod -l app.kubernetes.io/component=gateway --field-selector status.phase=Running
curl -H "Host: careerlens.local" http://localhost:8080/api/auth/me    # still 401 — no downtime
kubectl get pods -l app.kubernetes.io/component=gateway               # replacement Running ~40s
```

Verified: killing a gateway pod caused **zero** failed requests (the second replica served
them) and Kubernetes replaced it automatically.

Four layers of recovery, worth naming separately:

1. **Process** — container exits → restartPolicy restarts it
2. **Probe** — process wedged but alive → livenessProbe restarts it
3. **Replica** — pod/node lost → Deployment schedules a replacement elsewhere
4. **Release** — bad deploy → `helm rollback` (wired into CI's `on: failure`)

---

## Two bugs this deployment exposed

Both invisible until it actually ran — worth keeping as interview answers.

**1. Frontend had no `/health`.** The chart probes every service identically, but Next.js
had no such route, so readiness failed forever. Pods showed `Running` and logged `Ready`
while the Service had zero endpoints and the Ingress served nothing. Fix: a real health
route — deliberately shallow, because checking the database from the frontend's probe
would let a DB blip restart healthy frontend pods.

**2. Ingress controller on the wrong node.** kind's `extraPortMappings` exist only on the
control-plane, but the controller scheduled onto a worker — so nothing on the host could
reach it. Everything looked healthy; `curl` returned nothing. Fix: `nodeSelector` plus the
control-plane `NoSchedule` toleration (the selector alone leaves it Pending forever).

---

## Debugging commands worth knowing

```bash
kubectl get pods -o wide                    # which node is each pod on?
kubectl describe pod <name>                 # Events at the bottom = why it's not starting
kubectl logs <name> --previous              # logs from the crashed instance
kubectl get endpoints <svc>                 # EMPTY = readiness failing (the #1 cause)
kubectl exec -it <pod> -- sh                # shell inside
kubectl port-forward svc/careerlens-gateway 8000:8000
helm get manifest careerlens                # what was actually applied
helm history careerlens                     # revisions, for rollback
```

`kubectl get endpoints` deserves special mention: a Service with no endpoints is almost
always a failing readiness probe or a label-selector typo, and it's the fastest way to
tell those apart from an application bug.

---

## Next: getting this into a cloud

See [CLOUD_LEARNING_PLAN.md](CLOUD_LEARNING_PLAN.md). Short version: **k3s on an Oracle
Always Free ARM VM** is real Kubernetes at ₹0/month, and this chart deploys there
unchanged — only `imageRegistry`, `imagePullPolicy` and `ingress.host` differ.
