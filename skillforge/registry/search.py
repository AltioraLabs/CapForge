"""SkillForge Capability Search and Matcher Engine.

Provides lexical, tag-based, and semantic scoring to find matching capabilities
for a given task requirement or primitive name.
"""

from __future__ import annotations

import re
from typing import List, Tuple
from skillforge.core.models import Capability, CapabilityStatus
from skillforge.registry.store import CapabilityRegistry


class CapabilityMatcher:
    """Matches task requirements against the Capability Registry."""

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def find_matches(
        self,
        query: str,
        threshold: float = 0.50,
        limit: int = 5
    ) -> List[Tuple[Capability, float]]:
        """Find capabilities matching the search query, returned with similarity scores [0.0 - 1.0]."""
        all_caps = self.registry.list_capabilities(status=CapabilityStatus.ACTIVE)
        if not all_caps:
            # Fall back to include EXPERIMENTAL if no ACTIVE exist
            all_caps = self.registry.list_capabilities()

        query_terms = set(re.findall(r"\w+", query.lower()))
        results: List[Tuple[Capability, float]] = []

        for cap in all_caps:
            score = self._compute_similarity(query_terms, query.lower(), cap)
            if score >= threshold:
                results.append((cap, round(score, 3)))

        # Sort descending by score
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

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

        return min(1.0, score)
