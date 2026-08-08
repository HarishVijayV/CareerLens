"""
Verify the whole system, end to end, in one command:

    python check_setup.py

Checks infrastructure, every service, the warehouse, each credential, and the AI agents —
and for anything missing, prints exactly what to do about it. Nothing here mutates state,
so it's safe to run whenever something feels broken.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY = "http://localhost:8000"
ENV_PATH = Path(__file__).parent / "infra" / ".env"

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"
OK, FAIL, WARN = f"{GREEN}PASS{RESET}", f"{RED}FAIL{RESET}", f"{YELLOW}SKIP{RESET}"

results = {"pass": 0, "fail": 0, "skip": 0}


def report(status: str, name: str, detail: str = "") -> None:
    key = {OK: "pass", FAIL: "fail", WARN: "skip"}[status]
    results[key] += 1
    print(f"  [{status}] {name}" + (f"\n         {DIM}{detail}{RESET}" if detail else ""))


def load_env() -> dict:
    if not ENV_PATH.exists():
        print(f"{RED}infra/.env not found. Run: cp infra/.env.example infra/.env{RESET}")
        sys.exit(1)
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def http(path: str, method="GET", body=None, cookies=None, timeout=30):
    """Tiny HTTP helper — stdlib only, so this script runs with no dependencies."""
    req = urllib.request.Request(f"{GATEWAY}{path}", method=method)
    req.add_header("Content-Type", "application/json")
    if cookies:
        req.add_header("Cookie", cookies)
    data = json.dumps(body).encode() if body else None
    with urllib.request.urlopen(req, data, timeout=timeout) as resp:
        raw = resp.read().decode()
        set_cookie = resp.headers.get_all("Set-Cookie") or []
        parsed = json.loads(raw) if raw.strip().startswith(("{", "[")) else raw
        return resp.status, parsed, "; ".join(c.split(";")[0] for c in set_cookie)


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> None:
    env = load_env()
    print("CareerLens — setup check")

    # ---------------------------------------------------------------- services
    section("1. Services")
    for port, name in [(8000, "gateway"), (8001, "auth"), (8002, "agent"),
                       (8003, "jobs"), (8004, "notification")]:
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=10):
                report(OK, f"{name}-service (:{port})")
        except Exception:
            report(FAIL, f"{name}-service (:{port})", "cd infra && docker compose up -d")

    try:
        with urllib.request.urlopen("http://localhost:3000", timeout=20):
            report(OK, "frontend (:3000)")
    except Exception:
        report(FAIL, "frontend (:3000)", "cd infra && docker compose up -d frontend")

    # ---------------------------------------------------------------- auth flow
    section("2. Authentication")
    cookies = None
    try:
        _, _, cookies = http("/api/auth/login", "POST",
                             {"email": "harish@example.com", "password": "testpass1234"})
        if not cookies:
            raise RuntimeError("no cookies returned")
        report(OK, "login + cookies")
    except Exception as exc:
        report(FAIL, "login", f"{exc}")

    if cookies:
        try:
            _, me, _ = http("/api/auth/me", cookies=cookies)
            report(OK, "session (/auth/me)", f"logged in as {me.get('email')}")
        except Exception as exc:
            report(FAIL, "session", str(exc))

    # ---------------------------------------------------------------- warehouse
    section("3. Data warehouse")
    if cookies:
        try:
            _, ov, _ = http("/api/analytics/overview", cookies=cookies)
            postings = ov.get("total_postings", 0)
            if postings:
                report(OK, "warehouse populated",
                       f"{postings:,} postings, {ov.get('total_companies', 0):,} companies")
            else:
                report(FAIL, "warehouse empty", "cd pipeline && python run_pipeline.py")
        except Exception as exc:
            report(FAIL, "analytics", str(exc))

        try:
            _, res, _ = http("/api/jobs/search?skill=Spark&limit=1", cookies=cookies)
            report(OK, "job search", f"{res.get('total', 0):,} postings require Spark")
        except Exception as exc:
            report(FAIL, "job search", str(exc))

        try:
            _, res, _ = http("/api/jobs/search?pay_band=above_market&limit=1", cookies=cookies)
            report(OK, "ML pay-band scoring", f"{res.get('total', 0):,} above market")
        except Exception as exc:
            report(WARN, "ML scoring", "run: python run_pipeline.py --only mllib,load,dbt")

    # ---------------------------------------------------------------- credentials
    section("4. Credentials")
    provider = env.get("LLM_PROVIDER", "")
    key_name = {"fireworks": "FIREWORKS_API_KEY", "gemini": "GEMINI_API_KEY",
                "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)

    if not key_name:
        report(FAIL, "LLM_PROVIDER", f"'{provider}' is not a known provider")
    elif not env.get(key_name):
        report(FAIL, f"{key_name} missing",
               "REQUIRED for AI features — see docs/CREDENTIALS.md step 1")
    else:
        report(OK, f"LLM key present ({provider})")

    if env.get("ADZUNA_APP_ID") and env.get("ADZUNA_APP_KEY"):
        report(OK, "Adzuna keys present", "India + USA job ingestion enabled")
    else:
        report(WARN, "Adzuna keys missing", "optional — without them only Remotive is fetched")

    if env.get("GOOGLE_CLIENT_ID") and env.get("GOOGLE_CLIENT_SECRET"):
        report(OK, "Google OAuth configured", "Gmail tracking available")
    else:
        report(WARN, "Google OAuth missing", "optional — Gmail tracking disabled")

    if env.get("JWT_SECRET_KEY", "").startswith("change_me"):
        report(FAIL, "JWT_SECRET_KEY is the default", "generate a real one before any deploy")
    else:
        report(OK, "JWT secret set")

    # ---------------------------------------------------------------- agents
    section("5. AI agents (needs the LLM key)")
    if cookies and key_name and env.get(key_name):
        try:
            # Deterministic agent + a question answerable purely from warehouse data, so a
            # failure here points at the LLM/tool wiring rather than at a vague prompt.
            _, ans, _ = http("/api/agents/ask", "POST",
                             {"message": "Which 3 skills pay the most above average?",
                              "agent": "market_analyst"},
                             cookies=cookies, timeout=120)
            tools = [t["tool"] for t in ans.get("tool_calls", [])]
            if tools:
                report(OK, "agent ran and called tools", f"tools: {', '.join(tools)}")
            else:
                report(WARN, "agent answered without calling tools",
                       "the MODEL likely doesn't support tool-calling — try another "
                       "FIREWORKS_MODEL (see docs/CREDENTIALS.md)")
            print(f"\n{DIM}         answer: {str(ans.get('answer'))[:220]}...{RESET}")
        except urllib.error.HTTPError as exc:
            report(FAIL, "agent call", f"HTTP {exc.code} — {exc.read().decode()[:200]}")
        except Exception as exc:
            report(FAIL, "agent call", str(exc))
    else:
        report(WARN, "agents", "skipped — no LLM key configured")

    # ---------------------------------------------------------------- resume
    section("6. Resume workspace")
    if cookies:
        try:
            _, active, _ = http("/api/resume/active", cookies=cookies)
            if active.get("exists"):
                report(OK, "resume stored",
                       f"{len(active.get('content_text') or '')} chars, "
                       f"LaTeX: {'yes' if active.get('content_latex') else 'no'}")
            else:
                report(WARN, "no resume uploaded", "upload one at http://localhost:3000/resume")
        except Exception as exc:
            report(FAIL, "resume endpoint", str(exc))

    # ---------------------------------------------------------------- summary
    print(f"\n{'=' * 58}")
    print(f"  {GREEN}{results['pass']} passed{RESET}   "
          f"{RED}{results['fail']} failed{RESET}   "
          f"{YELLOW}{results['skip']} skipped/optional{RESET}")
    print("=" * 58)

    if results["fail"] == 0:
        print(f"{GREEN}Everything required is working.{RESET}")
    else:
        print(f"{RED}Fix the FAIL rows above.{RESET} Details: docs/CREDENTIALS.md")

    sys.exit(1 if results["fail"] else 0)


if __name__ == "__main__":
    # Windows terminals need this to interpret the ANSI colour codes.
    if os.name == "nt":
        os.system("")
    main()
