# ICRISAT GraphRAG User Guide

Welcome to the User Guide for the ICRISAT Knowledge Graph! This document explains how to use the Knowledge Graph and how to integrate it with your existing Dense RAG (Vector Database) applications.

## 1. The Core Data
The knowledge graph is stored in `data/graph_6k.db` (a SQLite database). It contains three core tables:
- **`nodes`**: Entities like Crops (e.g. `PEARL MILLET`), Traits (`DROUGHT RESISTANCE`), and Papers (`paper_12942`).
- **`edges`**: The relationships connecting the nodes (e.g. `PEARL MILLET` -[`HAS_TRAIT`]-> `DROUGHT RESISTANCE`).
- **`communities`**: High-level, AI-generated reports that summarize large thematic clusters of research.

## 2. Running the Hybrid GraphRAG Query Tool
We have provided a query script (`graph/query_graph.py`) that acts as a bridge between your application and the SQLite database.

### Basic Usage
To query the graph, simply pass your natural language question to the script:
```bash
source venv/bin/activate
PYTHONPATH=. python3 graph/query_graph.py "What genes are associated with drought resistance in pearl millet?" --hops 1
```

### What happens under the hood?
1. **Semantic Extraction**: The script sends your query to the Gemini LLM to extract the core entities (e.g. `PEARL MILLET`, `DROUGHT RESISTANCE`).
2. **Graph Traversal**: It maps those entities to the graph and traverses out by the number of `--hops` you specified.
3. **Paper Aggregation**: It finds all the Research Papers connected to your entities within those hops.
4. **Community Context**: It identifies the overarching research community (e.g. *Genomic Architecture of Yield*) and pulls the executive summary.

---

## 3. Integrating with your existing Dense RAG Setup
If you already have a Vector Database (like Milvus, Pinecone, or Chroma) and are using LangChain/LlamaIndex, you can use `query_graph.py` to massively boost your LLM's accuracy.

Vector databases are great at finding specific paragraphs, but terrible at connecting dots across multiple papers. GraphRAG solves this.

### Python Integration Example
Instead of running it via terminal, import the engine directly into your Python backend:

```python
from graph.query_graph import GraphQueryEngine

# 1. Initialize the Graph Engine
graph_engine = GraphQueryEngine(db_path="data/graph_6k.db")
user_question = "What is the relationship between drought and aflatoxin in groundnut?"

# 2. Fetch the Graph Context
graph_context = graph_engine.query(user_question, hops=1)

# 3. Fetch your Dense RAG vector chunks (your existing code)
vector_chunks = my_vector_db.similarity_search(user_question, k=5)

# 4. Inject both into your final LLM Prompt
final_prompt = f"""
You are an expert ICRISAT agricultural researcher. Answer the user's question using ONLY the context provided below. 

USER QUESTION: {user_question}

=== DENSE TEXT CONTEXT ===
{vector_chunks}

=== KNOWLEDGE GRAPH CONTEXT ===
{graph_context}
"""

# Send to your LLM (OpenAI, Gemini, Claude, etc.)
response = llm.generate(final_prompt)
```

### Why do this?
By injecting the `graph_context`, your LLM will receive a structured "map" of how the isolated vector chunks relate to each other. It will also receive a global summary of the entire research topic, allowing it to provide comprehensive answers that span decades of research!

## 4. Visualizing the Graph
If you want to physically explore the 3D graph in your browser:
```bash
source venv/bin/activate
uvicorn server.app:app --host 0.0.0.0 --port 8090
```
Open `http://localhost:8090` in your web browser. You can click on nodes to see their connections and read their detailed summaries in the side panel.
