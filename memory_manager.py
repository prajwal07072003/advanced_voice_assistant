import os
from sentence_transformers import SentenceTransformer
import chromadb
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class MemoryManager:
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.client = chromadb.PersistentClient(path=os.getenv("CHROMA_DB_PATH", "./chroma_db"))
        self.collection = self.client.get_or_create_collection(
            name="conversation_history",
            metadata={"hnsw:space": "cosine"}
        )
        self.context_window = 5  # Remember last 5 exchanges

    def _generate_id(self):
        return f"mem_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    def remember(self, user_input: str, ai_response: str, metadata: dict = None):
        """Store conversation context with semantic embedding"""
        embedding = self.model.encode(f"{user_input} {ai_response}")
        self.collection.add(
            ids=self._generate_id(),
            embeddings=[embedding.tolist()],
            documents=ai_response,
            metadatas=metadata or {}
        )

    def recall(self, query: str, n_results: int = 3) -> list:
        """Retrieve relevant conversation history"""
        query_embedding = self.model.encode(query).tolist()
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        return [
            f"Previously: {doc}"
            for doc in results['documents'][0]
        ]

    def get_recent_history(self) -> list:
        """Get chronological recent history"""
        return self.collection.get(
            limit=self.context_window,
            include=["documents"]
        )['documents']