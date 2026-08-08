"""
Minimal Gmail REST client — deliberately raw `httpx` rather than google-api-python-client.

Why: that library pulls in a large dependency tree and hides the OAuth mechanics behind
`build('gmail', 'v1', credentials=...)`. Doing the token refresh and the two-step
list→get by hand is ~80 lines and means you can actually explain how Gmail access works,
which is the point of the project.

Gmail's API shape worth knowing:
  * messages.list returns only {id, threadId} — NOT content. You then fetch each message
    individually. That's why syncing is two phases and why the batch is capped.
  * message bodies are base64url-encoded and nested in a MIME part tree; multipart mail
    means walking the parts to find text/plain.
"""
import base64
from datetime import datetime, timedelta, timezone

import httpx

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailClient:
    def __init__(self, refresh_token: str, client_id: str, client_secret: str):
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._expires_at = datetime.now(timezone.utc)

    def _ensure_token(self) -> str:
        """Access tokens live ~1 hour; the refresh token mints new ones indefinitely.
        Refreshing lazily (only when expired) rather than on every call avoids hammering
        Google's token endpoint."""
        if self._access_token and datetime.now(timezone.utc) < self._expires_at:
            return self._access_token

        response = httpx.post(
            TOKEN_URL,
            data={
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()

        self._access_token = payload["access_token"]
        # Expire 60s early so a token can't lapse mid-request.
        self._expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=payload.get("expires_in", 3600) - 60
        )
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._ensure_token()}"}

    def list_message_ids(self, query: str, max_results: int = 50) -> list[str]:
        """`query` uses Gmail's own search syntax — the same thing you type in the Gmail
        search box. Letting Gmail do the filtering server-side is far cheaper than
        downloading an inbox and filtering locally."""
        response = httpx.get(
            f"{GMAIL_API}/messages",
            headers=self._headers(),
            params={"q": query, "maxResults": max_results},
            timeout=30.0,
        )
        response.raise_for_status()
        return [m["id"] for m in response.json().get("messages", [])]

    @staticmethod
    def _decode_part(data: str) -> str:
        # Gmail uses base64URL (- and _ instead of + and /), and strips padding.
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")

    def _extract_body(self, payload: dict) -> str:
        """Walk the MIME tree for the first text/plain part, falling back to text/html.
        A simple mail has its body at the top level; a multipart one nests it, sometimes
        several levels deep — hence the recursion."""
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")

        if mime_type == "text/plain" and body_data:
            return self._decode_part(body_data)

        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text

        if mime_type == "text/html" and body_data:
            return self._decode_part(body_data)

        return ""

    def get_message(self, message_id: str) -> dict:
        response = httpx.get(
            f"{GMAIL_API}/messages/{message_id}",
            headers=self._headers(),
            params={"format": "full"},
            timeout=30.0,
        )
        response.raise_for_status()
        message = response.json()

        headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
        body = self._extract_body(message["payload"])

        return {
            "id": message["id"],
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "date": headers.get("date", ""),
            "snippet": message.get("snippet", ""),
            # Truncated before it ever reaches the LLM: email threads can be enormous,
            # and the classification signal is almost always in the first screenful.
            # This is a cost control as much as a correctness one.
            "body": body[:3000],
        }
