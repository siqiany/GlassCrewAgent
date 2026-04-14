# tools/qdrant_search_tool.py
import os
import time
from crewai.tools import tool
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# 全局初始化 Qdrant 客户端和嵌入模型（只加载一次，避免重复）
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "glass_paper_chunks")
EMBED_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "intfloat/e5-base-v2")

_client = None
_embedder = None

def get_qdrant_client():
    global _client
    # Recreate client every time to handle connection closed issues
    try:
        _client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=10.0)
        # Test connection
        _client.get_collections()
    except Exception as e:
        print(f"Warning: Could not connect to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}: {e}")
        _client = None
    return _client

def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL_NAME)
    return _embedder

@tool("Search Papers in Qdrant")
def search_papers_in_qdrant(query: str, limit: int = 5, score_threshold: float = 0.5) -> str:
    """
    Search for relevant paper snippets from the local Qdrant vector database.

    This tool uses semantic search to find the most relevant text chunks from
    the pre‑indexed paper collection. It returns the top results with their
    source paper ID and similarity score.

    Args:
        query (str): The user's question or search term.
        limit (int, optional): Maximum number of results to return. Defaults to 5.
        score_threshold (float, optional): Minimum similarity score (0-1). Defaults to 0.5.

    Returns:
        str: A Markdown formatted string with the top relevant snippets,
              including paper ID and similarity score, or an error message.
    """
    # Convert string inputs to proper types (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.5
        return float(val)
    
    def to_int(val):
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return 5
        return int(val)
    
    limit = to_int(limit)
    score_threshold = to_float(score_threshold)
    
    try:
        client = get_qdrant_client()
        if client is None:
            return "Qdrant vector database is not available at this time. Falling back to other search methods."
        
        embedder = get_embedder()

        # 生成查询向量
        query_vector = embedder.encode(query).tolist()

        # 执行搜索
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True
        )

        # 获取点列表
        points = results.points
        
        if not points:
            return "No relevant information found. Try rephrasing your query or lowering the threshold."

        # 格式化为 Markdown
        markdown = "### 🔍 Search Results\n\n"
        for i, hit in enumerate(points, 1):
            payload = hit.payload
            score = hit.score
            paper_id = payload.get("paper_id", "Unknown") if payload else "Unknown"
            chunk_text = payload.get("chunk_text", "") if payload else ""

            markdown += f"#### Result {i} (score: {score:.3f})\n"
            markdown += f"- **Paper ID**: `{paper_id}`\n"
            markdown += f"- **Snippet**: {chunk_text[:500]}{'...' if len(chunk_text) > 500 else ''}\n\n"

        return markdown

    except Exception as e:
        return f"Error during search: {str(e)}"