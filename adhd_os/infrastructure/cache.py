import hashlib
import json
import logging
import math
from collections import Counter
from typing import Dict, List, Optional

import numpy as np

from adhd_os.models.schemas import DecompositionPlan
from adhd_os.infrastructure.database import DB

logger = logging.getLogger(__name__)

# ---- lightweight TF-IDF helpers (no extra dependencies) --------------------

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "to", "of", "in", "for", "on", "with", "at", "by", "it", "i",
    "my", "this", "that", "do", "if", "so", "not", "no", "up", "out",
})


def _tokenize(text: str) -> List[str]:
    """Lowercase, split, drop stop-words and short tokens."""
    return [
        w for w in text.lower().split()
        if len(w) > 1 and w not in _STOP_WORDS
    ]


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _tfidf_vectors(query_tokens: List[str], corpus: List[List[str]]):
    """Build TF-IDF vectors for *query_tokens* vs each doc in *corpus*.

    Returns (query_vec, list_of_doc_vecs) where vectors share the same vocab index.
    """
    # Build vocabulary from query + corpus
    vocab: Dict[str, int] = {}
    for tok in query_tokens:
        vocab.setdefault(tok, len(vocab))
    for doc in corpus:
        for tok in doc:
            vocab.setdefault(tok, len(vocab))

    n_docs = len(corpus) + 1  # +1 for query
    dim = len(vocab)

    # Document frequency
    df = np.zeros(dim)
    for tok in set(query_tokens):
        df[vocab[tok]] += 1
    for doc in corpus:
        for tok in set(doc):
            df[vocab[tok]] += 1

    idf = np.log((n_docs + 1) / (df + 1)) + 1  # smoothed IDF

    def _vec(tokens: List[str]) -> np.ndarray:
        tf = np.zeros(dim)
        counts = Counter(tokens)
        for tok, cnt in counts.items():
            if tok in vocab:
                tf[vocab[tok]] = cnt
        return tf * idf

    query_vec = _vec(query_tokens)
    doc_vecs = [_vec(doc) for doc in corpus]
    return query_vec, doc_vecs


# ---- TaskCache -------------------------------------------------------------

class TaskCache:
    """
    Semantic cache for task decompositions.
    Uses TF-IDF cosine similarity for fuzzy matching backed by SQLite.
    """

    SIMILARITY_THRESHOLD = 0.35  # minimum cosine similarity for a cache hit

    def _normalize_task(self, task: str) -> str:
        return task.lower().strip()

    def _compute_hash(self, task: str) -> str:
        normalized = self._normalize_task(task)
        return hashlib.md5(normalized.encode()).hexdigest()[:12]

    # --- retrieval ---

    def get(self, task: str, energy_level: int) -> Optional[DecompositionPlan]:
        """Exact-hash lookup, then fuzzy TF-IDF fallback."""
        # Fast path: exact match
        task_hash = self._compute_hash(task)
        plan_dict = DB.get_cached_plan(task_hash)
        if plan_dict:
            return DecompositionPlan(**plan_dict)

        # Slow path: semantic similarity over all cached descriptions
        all_rows = self._fetch_all_cache_rows()
        if not all_rows:
            return None

        query_tokens = _tokenize(task)
        if not query_tokens:
            return None

        corpus = [_tokenize(desc) for desc, _ in all_rows]
        query_vec, doc_vecs = _tfidf_vectors(query_tokens, corpus)

        best_score, best_idx = 0.0, -1
        for idx, dv in enumerate(doc_vecs):
            score = _cosine_similarity(query_vec, dv)
            if score > best_score:
                best_score, best_idx = score, idx

        if best_score >= self.SIMILARITY_THRESHOLD and best_idx >= 0:
            _, plan_json_str = all_rows[best_idx]
            try:
                return DecompositionPlan(**json.loads(plan_json_str))
            except Exception:
                pass

        return None

    # --- storage ---

    def store(self, task: str, plan: DecompositionPlan):
        self.store_with_energy(task, plan, energy=5)

    def store_with_energy(self, task: str, plan: DecompositionPlan, energy: int):
        task_hash = self._compute_hash(task)
        DB.cache_plan(task_hash, task, plan.model_dump_json(), energy)
        logger.debug("[CACHE] Stored decomposition for: %s", task[:30])

    # --- similarity search ---

    def get_similar_tasks(self, task: str, limit: int = 3) -> List[str]:
        """Returns the top-*limit* most similar cached task descriptions."""
        all_rows = self._fetch_all_cache_rows()
        if not all_rows:
            return []

        query_tokens = _tokenize(task)
        if not query_tokens:
            return []

        descriptions = [desc for desc, _ in all_rows]
        corpus = [_tokenize(d) for d in descriptions]
        query_vec, doc_vecs = _tfidf_vectors(query_tokens, corpus)

        scored = []
        for idx, dv in enumerate(doc_vecs):
            score = _cosine_similarity(query_vec, dv)
            if score > 0:
                scored.append((descriptions[idx], score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [desc for desc, _ in scored[:limit]]

    # --- helpers ---

    @staticmethod
    def _fetch_all_cache_rows() -> List[tuple]:
        """Returns list of (task_description, plan_json) from cache table."""
        with DB.get_connection() as conn:
            cursor = conn.execute(
                "SELECT task_description, plan_json FROM task_cache LIMIT 500"
            )
            return cursor.fetchall()


TASK_CACHE = TaskCache()
