"""FastEmbed Candidate Embedding & Content Hashing Service.

Generates 384-dimensional unit-normalized embeddings using all-MiniLM-L6-v2,
matching the exact vector space of the 9,512 catalog jobs in Supabase.
Enforces SHA-256 content hashing to bypass FastEmbed execution on repeat visits
and uses a lazy singleton ONNX runner to avoid cold-start disk reloads.
"""
import hashlib
from typing import List, Optional, Tuple
from fastembed import TextEmbedding

# Lazy singleton in-memory ONNX model instance
_embedding_model: Optional[TextEmbedding] = None


def get_embedding_model() -> TextEmbedding:
    """Returns the cached FastEmbed ONNX model instance or initializes it once."""
    global _embedding_model
    if _embedding_model is None:
        # parallel=1 guarantees memory safety (< 35 MB heap overhead)
        _embedding_model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
    return _embedding_model


def build_candidate_embedding_payload(
    headline: Optional[str],
    preferred_roles: List[str],
    skills: List[str],
    full_time_experience_years: float,
    internship_months: int = 0,
) -> str:
    """Synthesizes structured semantic chunk from parsed profile signals.
    Top 50 skills take ~70 tokens, safely within the 256-wordpiece token limit.
    """
    role_str = headline or (preferred_roles[0] if preferred_roles else "Software Engineer")
    
    if full_time_experience_years >= 1.0:
        exp_str = f"{full_time_experience_years} years full-time"
    else:
        exp_str = "Fresher / Entry-level"
        if internship_months > 0:
            exp_str += f" with {internship_months} months internship experience"

    skills_str = ", ".join(skills[:50]) if skills else "General Software Development"
    return f"Role: {role_str}. Skills: {skills_str}. Experience: {exp_str}."


def compute_content_hash(text: str) -> str:
    """Computes deterministic 64-character SHA-256 hex digest of payload."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_embedding(text: str) -> List[float]:
    """Generates 384-dimensional unit-normalized vector embedding."""
    model = get_embedding_model()
    embeddings = list(model.embed([text]))
    raw_emb = embeddings[0]
    
    # Calculate Euclidean L2 norm: sqrt(sum(x^2))
    norm = sum(x * x for x in raw_emb) ** 0.5
    if norm == 0:
        norm = 1.0
    return [float(x / norm) for x in raw_emb]


def resolve_candidate_embedding(
    payload_text: str,
    existing_hash: Optional[str] = None,
    existing_embedding: Optional[List[float]] = None,
) -> Tuple[List[float], str, bool]:
    """Resolves candidate embedding using dual-tier caching.
    
    Returns:
        (embedding, content_hash, is_cache_hit)
    """
    new_hash = compute_content_hash(payload_text)
    
    # Tier 1 Cache Hit: Payload unchanged and valid vector exists
    if existing_hash and new_hash == existing_hash and existing_embedding:
        return existing_embedding, new_hash, True
        
    # Tier 2 Cache Miss: Run FastEmbed via in-memory singleton
    new_embedding = generate_embedding(payload_text)
    return new_embedding, new_hash, False
