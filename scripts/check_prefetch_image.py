"""Run inside a DISPOSABLE candidate container, never against a live instance.

Creates synthetic memories and API keys in that container's configured database.
Invoke: docker exec -i <disposable-container> python - < scripts/check_prefetch_image.py
Requires the explicit environment flag GLYPHHOLD_DISPOSABLE_TEST=1.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

if os.environ.get("GLYPHHOLD_DISPOSABLE_TEST") != "1":
    raise SystemExit("Set GLYPHHOLD_DISPOSABLE_TEST=1 only in a disposable test container")

from app.core.auth import create_api_key
from app.storage.repositories.categories import create_category
from app.v2 import core


def request(path, token=None, data=None, extra_headers=None):
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(
        "http://127.0.0.1:5995" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
    )
    with urlopen(req, timeout=10) as response:
        return json.load(response)


health = request("/api/v1/health")
assert health["database"] == "ok"
kid, token = create_api_key(
    name="disposable candidate smoke",
    actor="smoke",
    description=None,
    scopes=["memories:read", "memories:write"],
)
core.set_connection(
    core.ADMIN,
    kid,
    {
        "default_space_id": "space_personal",
        "grants": [
            {"space_id": "space_personal", "can_read": True, "can_write": True},
            {"space_id": "space_general", "can_read": True, "can_write": True},
        ],
    },
)


def create(key, **fields):
    return request("/api/v2/memories", token, fields, {"Idempotency-Key": key})


food = create(
    "image-food", title="Tess dinner preferences", body="Tess avoids almonds and prefers Thai food."
)
runbook = create(
    "image-runbook",
    title="Storage recovery runbook",
    body="Storage recovery preparation. " * 250 + "Recovery command: RESTORE-VERIFIED.",
)
preference = create(
    "image-pref",
    title="Response style",
    body="Prefer concise UK English.",
    space_id="space_general",
    auto_prefetch_level="pinned",
)
category = create_category(name="Image manual only", allow_auto_prefetch=False)
manual = create(
    "image-manual", title="ManualProbe marker", body="ManualProbe only.", category_id=category["id"]
)


def recall(query, **kwargs):
    return request(
        "/api/v2/recall", token, {"query": query, "limit": 5, "max_chars": 2400, **kwargs}
    )


food_recall = recall("Please remind me what food Tess likes.")
assert food_recall["results"][0]["id"] == food["id"]
assert runbook["id"] not in {r["id"] for r in food_recall["results"]}
unrelated = recall("Calculate 51 times 13.")
assert unrelated["context"]["abstained"]
assert all(r["id"] == preference["id"] for r in unrelated["results"])
excluded = recall("ManualProbe")
assert manual["id"] not in {r["id"] for r in excluded["results"]}
recovery = recall("Storage recovery command")
row = next(r for r in recovery["results"] if r["id"] == runbook["id"])
assert row["excerpted"] and row["truncated"] and "RESTORE-VERIFIED" in row["body"]
assert recovery["character_count"] == sum(
    len(json.dumps(r, ensure_ascii=False)) for r in recovery["results"]
)
assert recovery["character_count"] <= 2400
full = request("/api/v2/memories/" + runbook["id"], token)
assert len(full["body"]) > 5000 and full["body"].endswith("RESTORE-VERIFIED.")
literal = recall('" OR (Tess NEAR NOT:*)')
assert any(r["id"] == food["id"] for r in literal["results"])

restricted_id, restricted_token = create_api_key(
    name="disposable restricted", actor="restricted", description=None, scopes=["memories:read"]
)
core.set_connection(
    core.ADMIN,
    restricted_id,
    {
        "default_space_id": "space_work",
        "grants": [{"space_id": "space_work", "can_read": True, "can_write": True}],
    },
)
hidden = request("/api/v2/recall", restricted_token, {"query": "Tess", "broaden": True})
assert hidden["results"] == [] and hidden["context"]["candidate_count"] == 0
timings = []
for _ in range(5):
    started = time.perf_counter()
    recall("Storage recovery command")
    timings.append(round((time.perf_counter() - started) * 1000, 2))
print(
    json.dumps(
        {
            "http_recall": True,
            "unrelated_topical_abstention": True,
            "category_exclusion": True,
            "permission_boundary": True,
            "literal_fts": True,
            "answer_excerpt": True,
            "full_record_preserved": True,
            "character_budget": True,
            "authenticated_http_ms": timings,
            "retrieval_sha256": hashlib.sha256(
                Path("/app/app/v2/retrieval.py").read_bytes()
            ).hexdigest(),
        }
    )
)
