# Auth & Security — What's Implemented and Why

## The full login flow, step by step

1. **Signup** — password is never stored as-is. It's hashed with **bcrypt** (via `passlib`),
   which includes a random salt automatically, so two users with the same password get
   completely different hashes stored. Even if the database leaks, raw passwords are never
   recoverable from it (bcrypt is deliberately slow, which makes brute-forcing expensive).

2. **Login** — the submitted password is hashed the same way and compared to the stored hash
   (never compare raw strings). On success, the Auth Service issues:
   - a short-lived **JWT access token** (15 min) — carries `user_id`, `role`, expiry; signed
     with a server secret so it can't be forged or edited.
   - a long-lived **refresh token** (7 days) — opaque random string, stored hashed in Postgres
     (and its raw form in Redis with a matching TTL), *not* a JWT — so it can be revoked
     server-side instantly (you can't revoke a JWT early without a blocklist, which is exactly
     why refresh tokens use a different mechanism).
   - Both are sent back as **httpOnly, Secure, SameSite=Lax cookies** — not localStorage. This
     matters: JavaScript can never read an httpOnly cookie, so a successful XSS attack still
     can't steal the tokens.

3. **Every subsequent request** — the Gateway's auth middleware reads the access-token cookie,
   verifies the JWT signature + expiry, and attaches the verified user identity to the request
   before forwarding downstream. Downstream services trust the Gateway's header, not the raw
   cookie — they never re-verify a JWT themselves.

4. **Access token expires** — the frontend calls `/auth/refresh`, which checks the refresh
   token against Redis/Postgres, and if valid, issues a brand-new access token (and rotates the
   refresh token — old one is invalidated, a new one issued). Refresh-token rotation is what
   lets you detect theft: if a refresh token is used twice, that's a signal it was stolen, and
   every session for that user can be force-logged-out.

5. **Logout** — deletes the refresh token from Redis/Postgres and clears both cookies. The
   access token itself still technically works until it naturally expires (15 min) — that's
   the accepted tradeoff of stateless JWTs, and worth being able to say out loud in an
   interview rather than pretending JWTs are instantly revocable.

## Sessions vs JWT — why both

A pure "JWT-only" system can't force-logout a user early. A pure "server-side session" system
doesn't scale as easily across services without a shared session store. This project uses both
deliberately: the **JWT** is the fast, stateless, verify-anywhere credential for normal
requests; the **session/refresh token in Redis** is the source of truth that lets you revoke,
track "logged in devices," and rotate safely. Explaining this tradeoff clearly is one of the
highest-value backend interview answers there is.

## RBAC (Role-Based Access Control)

Every user row has a `role` (`user`, `admin`). The JWT carries the role, and a small FastAPI
dependency (`require_role("admin")`) gates admin-only routes (e.g. viewing pipeline job status
for all users). Simple, but it's the real mechanism — not a placeholder.

## Rate limiting

Redis-backed sliding-window counter per `user_id` + route (e.g. max 20 agent calls/minute).
Implemented as Gateway middleware so every service is protected without repeating the logic.
Prevents both abuse and runaway LLM API costs.

## Other standard protections, and where they live

| Concern | Where handled | How |
|---|---|---|
| CORS | Gateway middleware | explicit allow-list of the frontend origin only |
| CSRF | Cookie config + double-submit token on state-changing routes | `SameSite=Lax` cookies + a CSRF token header checked on POST/PUT/DELETE |
| SQL injection | ORM (SQLAlchemy) with parameterized queries everywhere | never string-format raw SQL |
| XSS | React escapes output by default; CSP header set at Gateway | never `dangerouslySetInnerHTML` on user content |
| Input validation | Pydantic models on every FastAPI route | invalid input is rejected before it reaches business logic |
| Secrets | `.env` files locally (never committed), a real secrets manager in cloud phase | see `infra/.env.example` |

## OAuth (Google login + Gmail read access)

Handled via the standard OAuth2 Authorization Code flow: user is redirected to Google, grants
scoped access (`gmail.readonly` + basic profile), Google redirects back with a code, the Auth
Service exchanges it server-side for tokens (never exposed to the browser), and stores the
Google refresh token encrypted in Postgres so the Worker Service can poll Gmail later without
the user being present. This is also the answer to "how do you keep long-lived third-party
access safe" — the token that matters never touches the frontend at all.
