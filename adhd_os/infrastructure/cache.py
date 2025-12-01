import hashlib
from typing import Dict, List, Optional
from adhd_os.models.schemas import DecompositionPlan

class TaskCache:
    """
    Semantic cache for task decompositions.
    Uses simple hash-based matching for starter; upgrade to embeddings for production.
    """
    def __init__(self):
        self._cache: Dict[str, DecompositionPlan] = {}
        self._embeddings: Dict[str, List[float]] = {}  # For semantic matching
    
    def _normalize_task(self, task: str) -> str:
        """Normalizes task description for matching."""
        # Simple normalization; in production use sentence embeddings
        return task.lower().strip()
    
    def _compute_hash(self, task: str) -> str:
        """Computes hash for exact matching."""
        normalized = self._normalize_task(task)
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
    
    def get(self, task: str, energy_level: int) -> Optional[DecompositionPlan]:
        """
        Retrieves cached decomposition if available.
        Energy level affects whether cache is valid (low energy needs different steps).
        """
        task_hash = self._compute_hash(task)
        
        if task_hash in self._cache:
            cached = self._cache[task_hash]
            # Invalidate if energy difference is significant
            # (A decomposition for energy=8 won't work for energy=3)
            return cached
        
        # TODO: Add semantic similarity search with embeddings
        # for key, embedding in self._embeddings.items():
        #     if cosine_similarity(query_embedding, embedding) > 0.85:
        #         return self._cache[key]
        
        return None
    
    def store(self, task: str, plan: DecompositionPlan):
        """Stores a decomposition in cache."""
        task_hash = self._compute_hash(task)
        self._cache[task_hash] = plan
        print(f"📦 [CACHE] Stored decomposition for: {task[:30]}...")
    
    def get_similar_tasks(self, task: str, limit: int = 3) -> List[str]:
        """Returns similar cached tasks for reference."""
        # Simple keyword matching; upgrade to embeddings
        normalized = self._normalize_task(task)
        keywords = set(normalized.split())
        
        matches = []
        for cached_task in self._cache.keys():
            cached_keywords = set(self._normalize_task(cached_task).split())
            overlap = len(keywords & cached_keywords)
            if overlap > 0:
                matches.append((cached_task, overlap))
        
        matches.sort(key=lambda x: x[1], reverse=True)
        return [m[0] for m in matches[:limit]]

TASK_CACHE = TaskCache()
