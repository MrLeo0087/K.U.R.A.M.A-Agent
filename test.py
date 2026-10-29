import numpy as np
from typing import List, Dict
import logging

# Configure basic logging
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
        document embeddings. Returns the ``top_k`` most similar documents along with
        their similarity scores in descending order.

        Each result is a dictionary with the keys:
            - ``document``: the original document string
            - ``score``: cosine similarity score (float, range [-1, 1])

        Args:
            query_embedding: A list (or array‑like) representing the query vector.
            top_k: Number of top results to return.

        Returns:
            A list of dictionaries sorted by descending similarity.
        """
        if self.embeddings.size == 0:
            logger.warning("Search called on an empty vector store.")
            return []

        # Convert query to numpy array and ensure same dtype
        query_vec = np.asarray(query_embedding, dtype=np.float32)

        if query_vec.shape[0] != self.embeddings.shape[1]:
            raise ValueError(
                f"Dimension mismatch: query vector has dimension {query_vec.shape[0]}, "
                f"but stored embeddings have dimension {self.embeddings.shape[1]}."
            )

        # Normalize embeddings and query to unit vectors
        # Add a tiny epsilon to avoid division by zero
        eps = 1e-10
        doc_norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True) + eps
        normalized_docs = self.embeddings / doc_norms

        query_norm = np.linalg.norm(query_vec) + eps
        normalized_query = query_vec / query_norm

        # Cosine similarity is just dot product of normalized vectors
        similarities = normalized_docs @ normalized_query  # shape: (num_documents,)

        # Get indices of top_k similarities
        top_k = min(top_k, len(self.documents))
        top_indices = np.argpartition(-similarities, range(top_k))[:top_k]
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
