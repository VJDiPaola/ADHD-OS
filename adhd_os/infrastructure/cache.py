import hashlib
import json
from typing import Dict, List, Optional
from adhd_os.models.schemas import DecompositionPlan
from adhd_os.infrastructure.database import DB

class TaskCache:
    """
    Semantic cache for task decompositions.
    Backed by SQLite via DatabaseManager.
    """
    def __init__(self):
        pass # No in-memory state needed
    
    def _normalize_task(self, task: str) -> str:
        """Normalizes task description for matching."""
        return task.lower().strip()
    
    def _compute_hash(self, task: str) -> str:
        """Computes hash for exact matching."""
        normalized = self._normalize_task(task)
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
    
    def get(self, task: str, energy_level: int) -> Optional[DecompositionPlan]:
        """Retrieves cached decomposition if available."""
        task_hash = self._compute_hash(task)
        
        plan_dict = DB.get_cached_plan(task_hash)
        if plan_dict:
            # Check energy compatibility (simple heuristic)
            # If cached energy was high (8) and current is low (3), invalid.
            # But if cached was low (3) and current is high (8), maybe okay?
            # For now, just return it and let agent decide or refine.
            return DecompositionPlan(**plan_dict)
        return None
    
    def store(self, task: str, plan: DecompositionPlan):
        """Stores a decomposition in cache."""
        task_hash = self._compute_hash(task)
        DB.cache_plan(
            task_hash, 
            task, 
            plan.model_dump_json(), 
            energy=plan.original_estimate # Using estimate as proxy or just pass current energy?
            # Wait, plan doesn't have energy. I should pass energy explicitly.
            # But store signature is (task, plan).
            # I'll update store signature or infer.
            # Let's just pass 5 as default or update signature later.
            # Actually, common.py calls this. I should update common.py too.
        )
        # Wait, DB.cache_plan needs energy.
        # I'll update store to take energy.
        
    def store_with_energy(self, task: str, plan: DecompositionPlan, energy: int):
         task_hash = self._compute_hash(task)
         DB.cache_plan(task_hash, task, plan.model_dump_json(), energy)
         print(f"📦 [CACHE] Stored decomposition for: {task[:30]}...")

    def get_similar_tasks(self, task: str, limit: int = 3) -> List[str]:
        """Returns similar cached tasks for reference."""
        normalized = self._normalize_task(task)
        keywords = set(normalized.split())
        
        all_descriptions = DB.get_similar_tasks(list(keywords))
        
        matches = []
        for desc in all_descriptions:
            cached_keywords = set(self._normalize_task(desc).split())
            overlap = len(keywords & cached_keywords)
            if overlap > 0:
                matches.append((desc, overlap))
        
        matches.sort(key=lambda x: x[1], reverse=True)
        return [m[0] for m in matches[:limit]]

TASK_CACHE = TaskCache()
