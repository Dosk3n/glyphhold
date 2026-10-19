"""Bounded automatic recall. Explicit search remains available for wider discovery.

No inference service, embeddings, implicit scope expansion or writes are needed.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
import unicodedata
from itertools import pairwise

from app.storage.db import connection

# Grammatical/conversational words, rather than names or domain-specific synonyms.
# Negation is retained: this tokenizer does not claim to resolve natural-language exclusions.
FILLER = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "so",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "onto",
        "to",
        "with",
        "i",
        "me",
        "my",
        "mine",
        "myself",
        "we",
        "us",
        "our",
        "ours",
        "you",
        "your",
        "yours",
        "yourself",
        "he",
        "him",
        "his",
        "she",
        "her",
        "hers",
        "it",
        "its",
        "itself",
        "they",
        "them",
        "their",
        "theirs",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "am",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "doing",
        "have",
        "has",
        "had",
        "having",
        "can",
        "could",
        "would",
        "should",
        "will",
        "shall",
        "may",
        "might",
        "must",
        "need",
        "needs",
        "want",
        "wanted",
        "like",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        "any",
        "anything",
        "something",
        "everything",
        "please",
        "thanks",
        "thank",
        "hello",
        "hi",
        "morning",
        "evening",
        "again",
        "also",
        "just",
        "really",
        "very",
        "actually",
        "about",
        "around",
        "out",
        "up",
        "down",
        "over",
        "under",
        "before",
        "after",
        "now",
        "next",
        "last",
        "first",
        "still",
        "only",
        "tell",
        "explain",
        "remind",
        "remember",
        "know",
        "think",
        "thinking",
        "wondering",
        "look",
        "looking",
        "check",
        "find",
        "get",
        "gets",
        "got",
        "give",
        "make",
        "help",
        "try",
        "use",
        "uses",
        "using",
        "used",
        "usually",
        "normally",
        "sort",
        "much",
        "many",
        "some",
        "such",
        "more",
        "most",
        "other",
        "another",
        "different",
        "each",
        "all",
        "both",
        "either",
        "pre",
    ]
)
WORD = re.compile(r"[^\W_]+", re.UNICODE)
SCOPE_WORDS = frozenset({"home", "office", "work", "personal", "general"})
IDENTIFIER = re.compile(
    r"(?<![\w.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
    r"(?:[a-z]{2,63}|\d{1,3})(?::\d{1,5})?(?![\w-]|\.[\w-])",
    re.IGNORECASE,
)


def fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)
    )


def stem(word: str) -> str:
    # Conservative inflections; no arbitrary name prefix or substring matching.
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 6 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 5 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def words(text: str) -> set[str]:
    return {stem(w) for w in WORD.findall(fold(text))}


def ipv6_values(text: str) -> set[str]:
    values = set()
    for token in re.findall(r"[0-9a-fA-F:]{3,}", text):
        try:
            values.add(str(ipaddress.IPv6Address(token)))
        except ipaddress.AddressValueError:
            continue
    return values


def prepare(query: str) -> tuple[list[str], list[str], list[str]]:
    folded = fold(query)
    identifiers = list(dict.fromkeys(IDENTIFIER.findall(folded)))[:16]
    # IPv6 is a separate token shape. Validate to avoid interpreting ordinary colons.
    for value in sorted(ipv6_values(query)):
        if value not in identifiers:
            identifiers.append(value)
    tokens = list(dict.fromkeys(w for w in WORD.findall(folded) if len(w) > 1 and w not in FILLER))[
        :64
    ]
    terms = list(dict.fromkeys(stem(w) for w in tokens))
    # FTS indexes original forms, so query both original and conservative inflection.
    fts_terms = list(dict.fromkeys(tokens + terms))[:128]
    if identifiers:
        fts_terms = list(
            dict.fromkeys(
                fts_terms + [token for value in identifiers for token in WORD.findall(value)]
            )
        )[:128]
    return terms, fts_terms, identifiers


def phrases(query: str) -> list[str]:
    tokens = WORD.findall(fold(query))
    return list(
        dict.fromkeys(
            f"{left} {right}"
            for left, right in pairwise(tokens)
            if len(left) > 1 and len(right) > 1 and left not in FILLER and right not in FILLER
        )
    )[:16]


def excerpt(body: str, terms: list[str], budget: int) -> str:
    """Select bounded matching passages and a tail; never invent or paraphrase facts."""
    if len(body) <= budget:
        return body
    if budget < 40:
        return body[: max(0, budget)]
    spans = []
    for start in range(0, len(body), 400):
        end = min(len(body), start + 480)
        text = body[start:end]
        score = len(set(terms) & words(text))
        spans.append((score, start, end))
    spans.sort(key=lambda value: (-value[0], value[1]))
    # Reserving tail context avoids always discarding commands/conclusions at the end.
    tail_size = min(200, max(40, budget // 4))
    start = spans[0][1]
    main_size = budget - tail_size - 7
    end = min(len(body), start + main_size)
    main = body[start:end]
    if end >= len(body) - tail_size:
        return body[max(0, len(body) - budget) :]
    return main + "\n[…]\n" + body[-tail_size:]


def pack(record: dict, terms: list[str], budget: int) -> dict | None:
    from app.v2 import core

    full = core._bounded_result(record, budget)
    if full is None or not full.get("truncated"):
        return full
    prepared = dict(record)
    prepared["summary"] = excerpt(record.get("summary") or "", terms, min(180, budget // 5)) or None
    prepared["source"] = (record.get("source") or "")[:80] or None
    prepared["body"] = ""
    header = core._bounded_result(prepared, max(0, budget - 45))
    if header is None:
        return None
    available = max(0, budget - 45 - len(json.dumps(header, ensure_ascii=False)))
    for _ in range(8):
        prepared["body"] = excerpt(record["body"], terms, available)
        bounded = core._bounded_result(prepared, max(0, budget - 45))
        if bounded is None:
            return None
        if bounded.get("body", "") == prepared["body"]:
            bounded.update(truncated=True, excerpted=True)
            return bounded if len(json.dumps(bounded, ensure_ascii=False)) <= budget else None
        available = max(
            0, available - max(16, len(prepared["body"]) - len(bounded.get("body", "")))
        )
    return None


def recall(
    p,
    query: str,
    space_id=None,
    broaden=False,
    limit=10,
    max_chars=12000,
    subject_ids=None,
    session_id=None,
) -> dict:
    from app.v2 import core

    core.check_scope(p, "memories:read")
    active = core.resolve_space(p, space_id, session_id=session_id)
    allowed = core.readable_spaces(p)
    spaces = list(allowed) if broaden else [active]
    if "space_general" in allowed and "space_general" not in spaces:
        spaces.append("space_general")
    terms, fts_terms, identifiers = prepare(query)
    query_phrases = phrases(query)
    marks = ",".join("?" for _ in spaces)
    select = "SELECT m.*,s.name AS space_name,cat.name AS category_name"
    joins = (
        " JOIN gh2_spaces s ON s.id=m.space_id JOIN memory_categories cat ON cat.id=m.category_id "
    )
    where = (
        f"m.space_id IN ({marks}) AND m.archived=0 AND m.superseded_by IS NULL "
        "AND m.merged_into IS NULL AND (m.stale=0 OR m.record_type='fact') "
        "AND m.auto_prefetch_level!='never' AND cat.allow_auto_prefetch=1"
    )
    candidate_limit = min(2000, max(256, limit * 32))
    entity_terms = set()
    linked_subjects = set()
    folded_query = " " + " ".join(WORD.findall(fold(query))) + " "
    with connection() as c:
        subjects = c.execute(
            "SELECT id,name,aliases_json FROM gh2_subjects WHERE space_id IN (" + marks + ")",
            spaces,
        ).fetchall()
        linked_subjects.update(set(subject_ids or []) & {row["id"] for row in subjects})
        for subject in subjects:
            for alias in [subject["name"], *json.loads(subject["aliases_json"])]:
                phrase = " ".join(WORD.findall(fold(alias)))
                if phrase and " " + phrase + " " in folded_query:
                    entity_terms |= words(alias)
                    linked_subjects.add(subject["id"])
                    fts_terms = list(
                        dict.fromkeys(fts_terms + WORD.findall(fold(subject["name"])))
                    )[:128]
        if fts_terms:
            # Every term is quoted: client text cannot become an FTS operator.
            fts = " OR ".join('"' + term.replace('"', '""') + '"' for term in fts_terms)
            if query_phrases:
                fts += " OR " + " OR ".join('"' + phrase + '"' for phrase in query_phrases)
            rows = c.execute(
                select + ",bm25(memories_fts,8.0,4.0,1.0,6.0) AS fts_rank "
                "FROM memories_fts JOIN memories m ON m.rowid=memories_fts.rowid"
                + joins
                + " WHERE memories_fts MATCH ? AND "
                + where
                + " ORDER BY fts_rank,m.updated_at DESC,m.id LIMIT ?",
                [fts, *spaces, candidate_limit],
            ).fetchall()
        else:
            rows = []
        if linked_subjects:
            placeholders = ",".join("?" for _ in linked_subjects)
            related = c.execute(
                select
                + ",0.0 AS fts_rank FROM memories m"
                + joins
                + " WHERE "
                + where
                + " AND EXISTS (SELECT 1 FROM json_each(m.subject_ids_json) "
                "WHERE value IN (" + placeholders + ")) ORDER BY m.updated_at DESC,m.id LIMIT ?",
                [*spaces, *sorted(linked_subjects), candidate_limit],
            ).fetchall()
            existing = {row["id"] for row in rows}
            rows = list(rows) + [row for row in related if row["id"] not in existing]
        pins = c.execute(
            select
            + ",0.0 AS fts_rank FROM memories m"
            + joins
            + " WHERE "
            + where
            + " AND m.space_id='space_general' AND m.auto_prefetch_level='pinned'"
            " ORDER BY m.updated_at DESC,m.id LIMIT ?",
            [*spaces, max(1, limit // 4)],
        ).fetchall()
    # Unregistered names can still be exact whole-word title anchors. Capitalization
    # identifies candidate names but never authorizes or expands their scope.
    query_tokens = WORD.findall(query)
    entity_terms |= {
        stem(fold(token))
        for token in query_tokens[1:]
        if token[0].isupper() and fold(token) not in FILLER | SCOPE_WORDS
    }
    for row in rows:
        title_tokens = WORD.findall(row["title"])
        if title_tokens and title_tokens[0][0].isupper():
            leading = stem(fold(title_tokens[0]))
            if leading in terms and leading not in FILLER | SCOPE_WORDS and len(leading) > 2:
                entity_terms.add(leading)
    scores = []
    for row in rows:
        record = core.decode(row)
        text = " ".join(
            [record["title"], record["summary"] or "", record["body"], " ".join(record["tags"])]
        )
        matches = set(terms) & words(text)
        # Scattered common words in a long document are weaker evidence than a
        # coherent passage. Title and confirmed entity matches remain explicit anchors.
        passage_matches = max(
            (
                len(set(terms) & words(text[start : start + 480]))
                for start in range(0, len(text), 400)
            ),
            default=0,
        )
        exact_ids = [
            value
            for value in identifiers
            if value in ipv6_values(text)
            or re.search(r"(?<![\w.-])" + re.escape(value) + r"(?![\w-]|\.[\w-])", fold(text))
        ]
        subject_match = bool(linked_subjects & set(record["subject_ids"]))
        # Identifier requests must match the whole identifier, never its shared octets.
        if identifiers and not exact_ids:
            continue
        title_phrase = any(
            " " + phrase + " " in " " + " ".join(WORD.findall(fold(record["title"]))) + " "
            for phrase in query_phrases
        )
        anchor = bool(matches & entity_terms) or subject_match or bool(exact_ids) or title_phrase
        if not matches and not exact_ids and not subject_match:
            continue
        if len(terms) > 1 and passage_matches < max(2, math.ceil(len(terms) * 0.35)) and not anchor:
            continue
        # BM25 leads. Small, bounded multipliers cannot let word counts dominate it.
        priority = {"low": 0.9, "normal": 1.0, "high": 1.08, "pinned": 1.12}[
            record["auto_prefetch_level"]
        ]
        score = max(1.0 if subject_match else 0.0, -float(record["fts_rank"])) * priority
        score *= 1.3 if anchor else 1.0
        score *= 1.15 if subject_match else 1.0
        scores.append((score, record))
    scores.sort(key=lambda item: (-item[0], item[1]["id"]))
    seen = set()
    unique = []
    for item in scores:
        record = item[1]
        identity = (
            record["space_id"],
            fold(record["title"]),
            " ".join(fold(record["body"]).split()),
            record["record_type"],
            tuple(sorted(record["subject_ids"])),
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(item)
    scores = unique
    if scores:
        floor = scores[0][0] * 0.22
        scores = [item for item in scores if item[0] >= floor]
    # Global pins are bounded background, not candidates that can crowd out topical hits.
    global_pins = [core.decode(r) for r in pins]
    pin_ids = {r["id"] for r in global_pins}
    topical = [r for _, r in scores if r["id"] not in pin_ids]
    capacity = max(1, min(limit, max_chars // 550))
    if topical:
        global_pins = global_pins[: max(0, capacity - 1)]
    selected = topical[: max(0, capacity - len(global_pins))] + global_pins[:capacity]
    results = []
    used = 0
    for index, record in enumerate(selected):
        # Share space before packing: an early long record cannot consume later shares.
        budget = (max_chars - used) // (len(selected) - index)
        if topical and record["id"] in pin_ids:
            budget = min(budget, 480)
        item = pack(record, terms, budget)
        if item:
            results.append(item)
            used += len(json.dumps(item, ensure_ascii=False))
    return {
        "results": results,
        "context": {
            "active_space_id": active,
            "default_space_id": core.default_space(p),
            "searched_space_ids": spaces,
            "expanded": bool(broaden),
            "retrieval_policy": "lexical-v2",
            "candidate_count": len(rows),
            "topical_count": len(topical),
            "abstained": not topical,
        },
        "estimated_tokens": math.ceil(used / 4),
        "character_count": used,
    }
