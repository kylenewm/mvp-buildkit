"""Cross-encoder reranker for Phase -1 search results.

Uses a lightweight transformer model to rerank search results by relevance
to the original query, selecting the top-k most relevant results.
"""

from typing import List, Tuple, Optional

# Model to use for reranking (fast, good quality)
DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Max chars per document to avoid latency issues on long pages
MAX_DOC_CHARS = 2500

# Max tokens for the model (MiniLM supports 512)
MAX_MODEL_TOKENS = 512


class RerankerError(Exception):
    """Error during reranking operations."""
    pass


class CrossEncoderReranker:
    """Reranks documents using a cross-encoder transformer model.
    
    The cross-encoder scores (query, document) pairs directly, which is
    more accurate than bi-encoder similarity for reranking.
    
    Usage:
        reranker = CrossEncoderReranker()
        ranked = reranker.rerank_with_scores(
            query="AI product manager ownership",
            docs=[("url1", "Title 1", "Content 1"), ...],
            top_k=3
        )
        # ranked is [(2, 0.95), (0, 0.82), (5, 0.71)] - (index, score) pairs
    """
    
    def __init__(self, model_name: str = DEFAULT_MODEL, max_length: int = MAX_MODEL_TOKENS):
        """Initialize the reranker with a cross-encoder model.
        
        Args:
            model_name: HuggingFace model ID for cross-encoder
            max_length: Max token length for model (default 512)
        
        Raises:
            RerankerError: If dependencies are missing or model fails to load
        """
        self.model_name = model_name
        self.max_length = max_length
        self._model = None
    
    def _load_model(self):
        """Lazy load the model on first use."""
        if self._model is not None:
            return
        
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise RerankerError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers torch"
            )
        
        try:
            self._model = CrossEncoder(self.model_name, max_length=self.max_length)
        except Exception as e:
            raise RerankerError(f"Failed to load model '{self.model_name}': {e}")
    
    def rerank_with_scores(
        self,
        query: str,
        docs: List[Tuple[str, str, str]],
        top_k: int = 3,
    ) -> List[Tuple[int, float]]:
        """Rerank documents by relevance to query, returning scores.
        
        Args:
            query: The search query
            docs: List of (url, title, text) tuples
            top_k: Number of top results to return
        
        Returns:
            List of (index, score) tuples, ordered by relevance (best first)
        
        Raises:
            RerankerError: If model loading or prediction fails
        """
        if not docs:
            return []
        
        self._load_model()
        
        # Build (query, doc_text) pairs for cross-encoder
        pairs = []
        for _, title, text in docs:
            # Combine title and text, truncate chars to reduce tokenization time
            doc_text = f"{title}\n\n{text}"[:MAX_DOC_CHARS]
            pairs.append((query, doc_text))
        
        try:
            # Get relevance scores from cross-encoder
            scores = self._model.predict(pairs)
        except Exception as e:
            raise RerankerError(f"Reranking failed: {e}")
        
        # Sort indices by score (descending)
        scored = list(enumerate(scores))
        scored.sort(key=lambda x: float(x[1]), reverse=True)
        
        # Return top_k (index, score) tuples
        effective_k = min(top_k, len(scored))
        return [(idx, float(score)) for idx, score in scored[:effective_k]]
    
    def rerank(
        self,
        query: str,
        docs: List[Tuple[str, str, str]],
        top_k: int = 3,
    ) -> List[int]:
        """Rerank documents by relevance to query (indices only).
        
        Convenience wrapper around rerank_with_scores that returns only indices.
        
        Args:
            query: The search query
            docs: List of (url, title, text) tuples
            top_k: Number of top results to return
        
        Returns:
            List of indices into `docs`, ordered by relevance (best first)
        """
        ranked = self.rerank_with_scores(query, docs, top_k)
        return [idx for idx, _ in ranked]


# Singleton instance for reuse (model loading is expensive)
_reranker_instance: Optional[CrossEncoderReranker] = None


def get_reranker() -> CrossEncoderReranker:
    """Get or create the singleton reranker instance."""
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = CrossEncoderReranker()
    return _reranker_instance

