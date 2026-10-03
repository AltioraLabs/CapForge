"""CapForge Capability Search and Matcher Engine.

Provides lexical, tag-based, and semantic scoring to find matching capabilities
for a given task requirement or primitive name.
"""

from __future__ import annotations

import re
from typing import List, Tuple
from capforge.core.models import Capability, CapabilityStatus
from capforge.registry.store import CapabilityRegistry


class CapabilityMatcher:
    """Matches task requirements against the Capability Registry."""

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def find_matches(
        self,
        query: str,
        threshold: float = 0.30,
        limit: int = 5,
        status: Optional[CapabilityStatus] = None,
    ) -> List[Tuple[Capability, float]]:
        """Find capabilities matching the search query, returned with similarity scores [0.0 - 1.0]."""
        if status:
            all_caps = self.registry.list_capabilities(status=status)
        else:
            all_caps = self.registry.list_capabilities()

        query_terms = set(re.findall(r"\w+", query.lower()))
        results: List[Tuple[Capability, float]] = []

        for cap in all_caps:
            score = self._compute_similarity(query_terms, query.lower(), cap)
            if cap.status == CapabilityStatus.ACTIVE:
                score = min(1.0, score + 0.15)
            if score >= threshold:
                results.append((cap, round(score, 3)))

        # Sort descending by score
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def match(self, query: str, top_k: int = 5, threshold: float = 0.1) -> list:
        """Find matching capabilities and return list of objects with .capability attribute."""
        class MatchResult:
            def __init__(self, capability: Capability, score: float):
                self.capability = capability
                self.score = score

        return [MatchResult(cap, score) for cap, score in self.find_matches(query, threshold=threshold, limit=top_k)]

    def _compute_similarity(self, query_terms: set[str], query_raw: str, cap: Capability) -> float:
        """Compute multi-factor similarity score between query and capability metadata."""
        score = 0.0

        # Exact ID match
        clean_id = cap.id.lower().replace("_", " ")
        if cap.id.lower() in query_raw or clean_id in query_raw:
            return 1.0

        # Exact name match
        if cap.name.lower() in query_raw:
            score += 0.80

        # Tag overlap
        cap_tags = set(t.lower() for t in cap.tags)
        tag_overlap = len(query_terms & cap_tags)
        if tag_overlap > 0:
            score += min(0.50, tag_overlap * 0.25)

        # Description term overlap
        desc_terms = set(re.findall(r"\w+", cap.description.lower()))
        desc_overlap = len(query_terms & desc_terms)
        if query_terms:
            overlap_ratio = desc_overlap / len(query_terms)
            score += min(0.40, overlap_ratio * 0.40)

        # Domain match
        if cap.domain.lower() in query_raw:
            score += 0.20

        # Character n-gram fuzzy similarity (sub-token and typo resilience)
        if len(query_raw) >= 3:
            ngrams_q = set(query_raw[i:i+3] for i in range(len(query_raw) - 2))
            corpus_text = f"{cap.id} {cap.name} {cap.description} {' '.join(cap.tags)}".lower()
            ngrams_c = set(corpus_text[i:i+3] for i in range(len(corpus_text) - 2))
            if ngrams_q and ngrams_c:
                coverage = len(ngrams_q & ngrams_c) / len(ngrams_q)
                score += coverage * 0.35

        return min(1.0, score)
