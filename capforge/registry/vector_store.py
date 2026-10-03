"""CapForge Hybrid Vector Embedding & Semantic Capability Search (discussion.mdx §30, §36, §50).

Provides zero-dependency dense vector embeddings, cosine distance similarity,
and hybrid lexical-vector retrieval for enterprise capability discovery.
"""

from __future__ import annotations

import hashlib
import math
import re

from capforge.core.models import Capability, CapabilityStatus
from capforge.registry.search import CapabilityMatcher
from capforge.registry.store import CapabilityRegistry


class DenseVectorEmbeddingEngine:
    """Generates normalized dense embedding vectors from text without requiring external deep learning models."""

    def __init__(self, dimension: int = 128):
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        """Compute an L2-normalized dense embedding vector using multi-hash feature projection."""
        tokens = re.findall(r"\w+", text.lower())
        vec = [0.0] * self.dimension

        if not tokens:
            return vec

        for token in tokens:
            # Word-level projection
            h_word = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h_word % self.dimension
            sign = 1.0 if ((h_word >> 8) & 1) == 0 else -1.0
            vec[idx] += sign * 1.5

            # Sub-word character trigrams for semantic morphological capture
            if len(token) >= 3:
                for i in range(len(token) - 2):
                    trigram = token[i : i + 3]
                    h_tri = int(hashlib.sha256(trigram.encode("utf-8")).hexdigest(), 16)
                    tri_idx = h_tri % self.dimension
                    tri_sign = 1.0 if ((h_tri >> 8) & 1) == 0 else -1.0
                    vec[tri_idx] += tri_sign * 0.5

        # L2-normalize vector
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 1e-9:
            vec = [x / norm for x in vec]
        return vec

    @staticmethod
    def cosine_similarity(v1: list[float], v2: list[float]) -> float:
        """Compute cosine similarity between two unit vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        return max(0.0, min(1.0, dot))


class SemanticVectorIndex:
    """In-memory vector store indexing capability embeddings for semantic retrieval.

    Auto-refreshes the embedding index when new capabilities are registered via
    the `on_capability_registered` callback hook.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        embedding_engine: DenseVectorEmbeddingEngine | None = None,
    ):
        self.registry = registry
        self.engine = embedding_engine or DenseVectorEmbeddingEngine(dimension=128)
        self.matcher = CapabilityMatcher(registry)
        self._vectors: dict[str, list[float]] = {}  # capability_id -> vector
        self._build_index()

    def _build_index(self) -> None:
        """Index all capabilities currently in the registry."""
        caps = self.registry.list_capabilities()
        for cap in caps:
            self.index_capability(cap)

    def rebuild_index(self) -> int:
        """Full rebuild from registry. Returns number of capabilities indexed."""
        self._vectors.clear()
        self._build_index()
        return len(self._vectors)

    def index_capability(self, capability: Capability) -> None:
        """Embed and store a single capability. Called on registration."""
        corpus = f"{capability.id} {capability.name} {capability.description} {capability.domain} {' '.join(capability.tags)}"
        self._vectors[capability.id] = self.engine.embed_text(corpus)

    def invalidate_capability(self, capability_id: str) -> None:
        """Remove a capability from the index (called on deletion or deprecation)."""
        self._vectors.pop(capability_id, None)

    def on_capability_registered(self, capability: Capability) -> None:
        """Hook to call after registry.register() to keep index fresh."""
        self.index_capability(capability)

    def search_vector(self, query: str, top_k: int = 5) -> list[tuple[Capability, float]]:
        """Search capabilities purely using dense vector cosine similarity."""
        q_vec = self.engine.embed_text(query)
        scores: list[tuple[Capability, float]] = []

        for cap_id, vec in self._vectors.items():
            cap = self.registry.get(cap_id)
            if cap:
                score = self.engine.cosine_similarity(q_vec, vec)
                scores.append((cap, round(score, 3)))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def hybrid_search(
        self,
        query: str,
        alpha: float = 0.5,
        top_k: int = 5,
        status: CapabilityStatus | None = None,
    ) -> list[tuple[Capability, float]]:
        """Hybrid retrieval blending lexical-fuzzy scores (1 - alpha) with dense vector scores (alpha)."""
        # Lexical matches
        lexical_raw = self.matcher.find_matches(query, threshold=0.0, limit=top_k * 3, status=status)
        lexical_dict = {cap.id: score for cap, score in lexical_raw}

        # Vector matches
        q_vec = self.engine.embed_text(query)
        caps = self.registry.list_capabilities(status=status)

        hybrid_scores: list[tuple[Capability, float]] = []
        for cap in caps:
            vec = self._vectors.get(cap.id)
            if not vec:
                vec = self.engine.embed_text(f"{cap.id} {cap.name} {cap.description}")
                self._vectors[cap.id] = vec

            vec_score = self.engine.cosine_similarity(q_vec, vec)
            lex_score = lexical_dict.get(cap.id, 0.0)

            # Blended score
            blended = ((1.0 - alpha) * lex_score) + (alpha * vec_score)

            # Boost active capabilities
            if cap.status == CapabilityStatus.ACTIVE:
                blended = min(1.0, blended + 0.1)

            hybrid_scores.append((cap, round(blended, 3)))

        hybrid_scores.sort(key=lambda x: x[1], reverse=True)
        return hybrid_scores[:top_k]
