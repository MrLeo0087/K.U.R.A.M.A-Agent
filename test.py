import numpy as np
from typing import List, Dict

class SimpleVectorStore:
    def __init__(self):
        self.documents: List[str] = []
        self.embeddings: np.ndarray = np.array([])

    def add_documents(self, docs: List[str], embeddings: List[List[float]]) -> None:
        """Adds documents and their corresponding vector embeddings to the store."""
        self.documents.extend(docs)
        new_embeddings = np.array(embeddings)
        if self.embeddings.size == 0:
            self.embeddings = new_embeddings
        else:
            self.embeddings = np.vstack((self.embeddings, new_embeddings))

    def search(self, query_embedding: List[float], top_k: int = 3) -> List[Dict[str, float]]:
        """
        TODO: Implement cosine similarity search between query_embedding 
        and self.embeddings. Return the top_k most similar documents 
        along with their similarity scores in descending order.
        """
        # === YOUR CODE HERE ===
        pass