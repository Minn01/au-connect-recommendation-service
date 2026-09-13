from functools import cache

from au_connect_recommendation_service.core.constants import EMBEDDING_MODEL_NAME
from sentence_transformers import SentenceTransformer



@cache
def get_embedding_model() -> SentenceTransformer:
    """Load the embedding model once and reuse it."""
    return SentenceTransformer(EMBEDDING_MODEL_NAME)