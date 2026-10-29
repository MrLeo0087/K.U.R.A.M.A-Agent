import numpy as np
from typing import List, Dict
import logging

# Configure a basic logger for this module
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleVectorStore:
    def __init__(self):
        self.documents: List[str] = []
        self.embeddings: np.ndarray = np.array([])

    def add_documents(self, docs: List[str], embeddings: List[List[float]]) -> None:
        """Adds documents and their corresponding vector embeddings to the store."""
        self.documents.extend(docs)
        new_embeddings = np.array(embeddings, dtype=np.float32)
        if self.embeddings.size == 0:
            self.embeddings = new_embeddings
        else:
            self.embeddings = np.vstack((self.embeddings, new_embeddings))

    def search(self, query_embedding: List[float], top_k: int = 3) -> List[Dict[str, float]]:
        """
        Perform a cosine similarity search between ``query_embedding`` and the stored
        ``self.embeddings``. Returns the ``top_k`` most similar documents together
        with their similarity scores, sorted in descending order.

        Each result is a dictionary with the keys:
            - ``document``: the original document string
            - ``score``: cosine similarity (float) between the query and the document vector

        Args:
            query_embedding: A list (or 1‑D array) representing the query vector.
            top_k: Number of top results to return.

        Returns:
            A list of dictionaries ordered by decreasing similarity.
        """
        if not self.documents:
            logger.warning("Search called on an empty store.")
            return []

        # Convert query to a NumPy array and ensure correct shape
        query_vec = np.asarray(query_embedding, dtype=np.float32)
        if query_vec.ndim != 1:
            raise ValueError("query_embedding must be a 1‑dimensional list or array.")

        # Guard against dimension mismatch
        if self.embeddings.shape[1] != query_vec.shape[0]:
            raise ValueError(
                f"Dimension mismatch: store embeddings have dimension {self.embeddings.shape[1]}, "
                f"but query embedding has dimension {query_vec.shape[0]}."
            )

        # Compute cosine similarity
        # Normalize vectors to unit length
        doc_norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        query_norm = np.linalg.norm(query_vec)

        # Avoid division by zero
        if query_norm == 0:
            raise ValueError("Query embedding is a zero vector; cannot compute cosine similarity.")
        doc_norms[doc_norms == 0] = 1e-10  # small epsilon to prevent NaNs

        normalized_docs = self.embeddings / doc_norms
        normalized_query = query_vec / query_norm

        similarities = normalized_docs @ normalized_query  # shape: (num_documents,)

        # Get indices of top_k scores
        top_k = min(top_k, len(self.documents))
        top_indices = np.argpartition(-similarities, top_k - 1)[:top_k]
        # Sort those top indices by actual similarity descending
        top_indices = top_indices[np.argsort(-similarities[top_indices])]

        results: List[Dict[str, float]] = []
        for idx in top_indices:
            results.append({
                "document": self.documents[idx],
                "score": float(similarities[idx])
            })

        logger.info("Search completed. Returned %d results.", len(results))
        return results
