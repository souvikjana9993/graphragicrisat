# ICRISAT GraphRAG: Technical Architecture & Pipeline

This document provides a step-by-step technical breakdown of how the ICRISAT Knowledge Graph is built, processed using the Microsoft GraphRAG pattern, and visualized.

---

## Phase 1: Data Ingestion & Metadata Processing
**Source**: EPrints / ICRISAT Open Access Repository.

1. **Metadata Scraping**: We fetch individual research paper metadata (titles, abstracts, authors, dates, keywords) and store them as JSON files in `data/raw_metadata/`.
2. **Registry System**: A centralized `Registry` class manages these files, extracting core entities like **Authors**, **Crops**, **Journals**, and **Geolocations** based on predefined rules and regex patterns.

---

## Phase 2: The Microsoft GraphRAG Pipeline
This is the "AI-Native" layer that goes beyond simple metadata to understand the *content* of the research.

### Step 1: Tuple-Based Extraction (`entity_extractor.py`)
- **Action**: We feed each abstract to **Gemma 4 31B**.
- **Logic**: Instead of JSON, we force the LLM to output precise text tuples: `("entity"|NAME|TYPE|DESC)`.
- **Normalization**: The LLM is commanded to **UPPERCASE** all entity names at the source. This ensures "QTL Mapping" and "QTL mapping" are seen as the same string.
- **Output**: Thousands of "raw" entity and relationship tuples.

### Step 2: Canonical Merging (`graph_merger.py`)
- **Action**: A high-performance **Pandas** script processes the raw tuples.
- **Logic**: It performs a `groupby(["name", "type"])`. 
- **De-duplication**: If "SORGHUM" appears in 50 different papers, Pandas collapses those 50 raw extractions into **one single Canonical Entity**.
- **Result**: A clean, deduplicated graph structure where each node represents a unique concept across the whole library.

### Step 3: Map-Reduce Summarization (`entity_summarizer.py`)
- **Action**: For entities with multiple descriptions (e.g., different perspectives on "Yield"), we run a second LLM pass.
- **Logic**: The LLM takes up to 30 differing descriptions for a single entity and synthesizes them into one **Canonical Description**.
- **Result**: Every node in the graph now has a high-fidelity, AI-written summary of what it means in the context of the entire ICRISAT dataset.

### Step 4: Hierarchical Leiden Clustering (`community_detector.py`)
- **Action**: We treat the entities and relationships as a mathematical graph.
- **Logic**: We run the **Leiden Algorithm** (via `leidenalg` and `igraph`).
- **Communities**: It groups nodes that are "tightly knit" into clusters.
- **Hierarchy**: We generate **Level 0 (Global Themes)** and **Level 1 (Sub-Themes)**.
- **Result**: Each node is assigned a Community ID (e.g., "Community 14" might be the 'Genetics' theme).

---

## Phase 3: System Integration & Visualization

### 1. Database Construction (`build_graph.py`)
We merge the **Traditional Metadata** (Authors, Journals) with the **LLM-Extracted Concepts** (Traits, Methods).
- **SQLite**: The final graph is stored in `data/graph.db` with two tables: `nodes` and `edges`.
- **JSON Export**: A massive JSON file is generated for the web frontend.

### 2. High-Performance Visualization (`viz/app.js`)
- **WebGL Engine**: We use the `force-graph` library (Canvas/WebGL) to render the nodes. This allows us to handle 50,000+ nodes smoothly on a standard laptop.
- **Physics**: A D3-based force simulation runs in the background to space the nodes out and prevent overlaps.
- **Interactivity**: 
  - Clicking a node fetches its details from the side panel.
  - Searching zooms the camera directly to a specific coordinate in the graph.

### 3. LLM Querying / RAG (`server/app.py`)
- **The Question**: You ask a question in the UI.
- **Context Injection**: The FastAPI backend queries the SQLite database for relevant papers/communities.
- **The Response**: Gemma reads this context and answers your question, providing clickable links that take you directly back to the nodes in the graph.

---

## Summary of the "GraphRAG" Advantage
Unlike standard "Search," this system doesn't just find keywords. It uses **Communities** to understand themes. Even if you don't search for "Genetics," the system *knows* that SORGHUM and QTL MAPPING belong to the same community, allowing it to provide much deeper and more relevant insights.
