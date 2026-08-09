"""
Kafka event publishing — and an honest note on why Kafka is here at all.

**When Kafka is NOT justified:** if one producer feeds exactly one consumer, Kafka is
strictly worse than a direct call or a database row. It adds a broker to operate, a
serialization format to version, and a whole class of delivery-semantics problems, in
exchange for nothing. Most "we use Kafka" portfolio projects are this case, and an
interviewer who knows the tool will spot it immediately.

**Why it IS justified here:** one `posting.discovered` event has *multiple independent
consumers that must not know about each other*:

  1. the warehouse loader        — persists it for analytics
  2. the match notifier          — alerts users whose profile matches
  3. (future) the embedder       — computes vectors for semantic search

Without a broker, the ingestion script would have to call all three itself — meaning it
breaks when the notifier is down, and adding a fourth consumer means editing the
producer. That fan-out with independent failure domains is exactly the problem a log-based
broker solves, and it's the honest justification for the dependency.

**The degradation rule:** ingestion must never fail because Kafka is down. Events are
best-effort here; the batch pipeline is the source of truth and can always reprocess from
the raw landing zone. Losing an event costs a notification, not data.
"""
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

def _resolve_bootstrap() -> str:
    """Pick the Kafka address that works from wherever this is running.

    Kafka advertises two addresses, and which one you need depends on which side of Docker
    you are on:

        kafka:9092        inside the compose network
        localhost:29092   from the host machine

    infra/.env sets `kafka:9092` because that is right for every service in the stack. But
    the pipeline usually runs on the HOST, where the name `kafka` does not resolve at all —
    so the producer failed to connect and every ingest quietly printed "Kafka unavailable",
    which reads as "Kafka isn't running" rather than "you're using the wrong address".

    Same shape of bug as pointing the browser at `gateway:8000`: a container-internal name
    used from outside it. Detected here rather than left to be configured, because getting
    it wrong produces silence, not an error.
    """
    configured = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
    if not configured:
        return ""

    # A hostname only Docker's DNS knows about, resolved from outside it, means we are on
    # the host and should use the advertised host listener instead.
    if "kafka:" in configured:
        import socket

        try:
            socket.gethostbyname("kafka")
        except OSError:
            return os.getenv("KAFKA_BOOTSTRAP_HOST", "localhost:29092")

    return configured


# Resolved when first needed, NOT at import.
#
# job_apis.py does `from events import publish_postings_discovered` at the top of the file
# and calls _load_env_file() further down — so a module-level lookup here ran before
# infra/.env had been read, found nothing, and disabled publishing for the whole run. The
# symptom was "Kafka unavailable", which sends you looking at the broker instead of at
# import order.
_bootstrap: str | None = None


def _bootstrap_servers() -> str:
    global _bootstrap
    if _bootstrap is None:
        _bootstrap = _resolve_bootstrap()
    return _bootstrap

TOPIC_POSTING_DISCOVERED = "posting.discovered"
TOPIC_APPLICATION_UPDATED = "application.updated"

_producer = None
_unavailable = False


def _get_producer():
    """Lazy connect. Import and connection both happen on first use so that neither a
    missing library nor a missing broker can stop a script that doesn't publish."""
    global _producer, _unavailable

    if _producer is not None or _unavailable:
        return _producer

    bootstrap = _bootstrap_servers()
    if not bootstrap:
        logger.info("KAFKA_BOOTSTRAP_SERVERS unset — event publishing disabled")
        _unavailable = True
        return None

    try:
        from kafka import KafkaProducer

        _producer = KafkaProducer(
            bootstrap_servers=bootstrap.split(","),
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
            # Wait for the leader only. Full ISR acks would be right for financial data;
            # for a discovery notification, latency matters more than durability, and the
            # batch pipeline is the real source of truth.
            acks=1,
            retries=2,
            request_timeout_ms=5000,
            max_block_ms=5000,   # never let a dead broker hang ingestion
        )
        logger.info("Kafka producer connected to %s", bootstrap)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kafka unavailable (%s) — continuing without events", exc)
        _unavailable = True

    return _producer


def publish(topic: str, key: str | None, value: dict[str, Any], timeout: float = 10.0) -> bool:
    """Publish and CONFIRM delivery. Returns whether the broker acknowledged it.

    `producer.send()` is asynchronous — it queues the record and hands back a future. An
    earlier version of this function returned True right after send(), which reported
    success for messages that never reached the broker at all (the advertised-listener
    misconfiguration in docker-compose meant every delivery silently failed while the
    producer looked perfectly healthy).

    Blocking on `.get()` costs latency, and for a high-throughput producer you'd instead
    attach callbacks and track failures asynchronously. At this volume, correct beats
    fast: a publisher that lies about delivery is worse than no publisher.
    """
    producer = _get_producer()
    if producer is None:
        return False

    try:
        future = producer.send(topic, key=key, value=value)
        future.get(timeout=timeout)   # raises if the broker never acknowledged
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("publish to %s failed: %s", topic, exc)
        return False


def publish_postings_discovered(postings: list[dict]) -> int:
    """Publish one event per newly-ingested posting.

    Keyed by posting_id, which matters: Kafka guarantees ordering *within a partition*,
    and keying by id means all events about the same posting land on the same partition
    and are therefore processed in order. Keying by nothing (round-robin) would let an
    update overtake its own create.
    """
    sent = 0
    for posting in postings:
        if publish(
            TOPIC_POSTING_DISCOVERED,
            key=posting.get("posting_id"),
            value={
                "posting_id": posting.get("posting_id"),
                "title": posting.get("title"),
                "company": posting.get("company"),
                "region": posting.get("region"),
                "required_skills": posting.get("required_skills", []),
                "source": posting.get("source"),
            },
        ):
            sent += 1

    if sent:
        producer = _get_producer()
        if producer:
            producer.flush(timeout=10)   # send() is async; flush before the script exits
        logger.info("published %d %s events", sent, TOPIC_POSTING_DISCOVERED)

    return sent
