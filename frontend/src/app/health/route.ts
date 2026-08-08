/**
 * Health endpoint for Kubernetes probes.
 *
 * Every backend service exposes /health, and the Helm chart probes all of them the same
 * way — but Next.js had no such route, so its readiness probe failed forever. The pods
 * ran fine and logged "Ready", yet the Service had no endpoints and the Ingress served
 * nothing. A confusing failure, because the app itself was healthy.
 *
 * Deliberately shallow: it reports that THIS process can serve requests, and nothing
 * more. It does not check the gateway or the database — if it did, a brief backend blip
 * would fail the frontend's liveness probe and restart a perfectly good pod, turning one
 * service's problem into two. Health checks should describe the thing being probed.
 */
export const dynamic = "force-dynamic"; // never cache or prerender a liveness signal

export async function GET() {
  return Response.json({ status: "ok", service: "frontend" });
}
