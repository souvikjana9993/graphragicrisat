# ICRISAT Knowledge Graph

Welcome to the **ICRISAT Knowledge Graph** repository. 

This project demonstrates the application of **GraphRAG (Retrieval-Augmented Generation via Knowledge Graphs)** to semi-arid agricultural research. We have processed a massive corpus of **over 6,500 scientific papers** from the ICRISAT library to extract, connect, and summarize global agricultural knowledge using large language models.

---

## 🎯 What is this?

Scientific research is often siloed in thousands of individual PDFs. This project automatically reads those papers and builds an interconnected web of knowledge (a Knowledge Graph). 

Instead of just searching for keywords, this graph understands that "Groundnut" is a *Crop*, "India" is a *Location*, and "Aflatoxin Contamination" is a *Trait/Issue*. It maps how these concepts relate to each other across decades of research.

### Key Features:
1. **AI-Driven Entity Extraction**: Extracted specific entities (Crops, Locations, Diseases, Breeding Methods) and their relationships directly from the text of 6,500+ papers using Google Gemma.
2. **Community Detection**: Used the Leiden algorithm to cluster related entities together into over 200 "Thematic Communities" (e.g., finding that Drought, Sorghum, and West Africa frequently appear together).
3. **AI Synthesis Reports**: Leveraged LLMs to automatically read the clusters and write high-level markdown reports summarizing the state of research for each community.
4. **Graph Database**: Compiled all findings into a queryable SQLite database and a JSON payload optimized for 3D web visualization.
5. **Hybrid RAG Integration**: A powerful query interface that injects both 1-hop/2-hop graph relationships and overarching community summaries into your existing vector database pipelines.

---

## 📂 What's in this Repository?

To keep the repository lightweight, the massive raw data files (over 12,000 PDFs and raw JSON extractions) are deliberately excluded. This repository contains the code and the **finalized pilot data**.

### 1. The Production Data (`data/`)
*   `graph_6k.db`: The finalized SQLite database. Contains all nodes, relationships, and the full AI-generated markdown reports for the research communities.
*   `graph_6k_export.json`: The compiled graph payload containing ~60,000 nodes and ~600,000 edges, formatted specifically for front-end 3D visualizers.

### 2. The Code (`graph/`)
*   `entity_extractor.py`: The data mining script that reads raw paper text and extracts nodes/edges.
*   `community_detector.py`: Runs the Leiden algorithm to group the graph into clusters.
*   `community_summarizer.py`: Feeds the clusters to the Gemini LLM to generate the final research reports.
*   `build_graph.py`: The compilation script that stitches everything into the final `.db` and `.json` outputs.

### 3. Usage & Integration
*   `query_graph.py`: The Hybrid RAG integration script. Use this to extract entities from user queries, traverse the graph, and retrieve community reports.

---

## 🚀 Quick Start & User Guide

You don't need to run the massive AI extraction pipeline to explore the data. You can query the finished database right away. For a comprehensive overview, please read the new **[USER_GUIDE.md](USER_GUIDE.md)**!

### 1. Running the GraphRAG Query Tool
If you want to integrate the graph with an LLM, run the query script to fetch the contextual injection block:
```bash
source venv/bin/activate
PYTHONPATH=. python3 graph/query_graph.py "drought resistance in pearl millet" --hops 1
```

### 2. Exploring the 3D Visualization
To visually explore the 6,000-paper graph:
```bash
source venv/bin/activate
uvicorn server.app:app --host 0.0.0.0 --port 8090
```
Then open `http://localhost:8090` in your browser.
