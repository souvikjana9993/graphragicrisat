# ICRISAT Knowledge Graph (Pilot Study)

Welcome to the **ICRISAT Knowledge Graph Pilot** repository. 

This project demonstrates the application of **GraphRAG (Retrieval-Augmented Generation via Knowledge Graphs)** to semi-arid agricultural research. We have processed a pilot subset of **1,000 scientific papers** from the ICRISAT library to extract, connect, and summarize global agricultural knowledge using large language models.

---

## 🎯 What is this?

Scientific research is often siloed in thousands of individual PDFs. This project automatically reads those papers and builds an interconnected web of knowledge (a Knowledge Graph). 

Instead of just searching for keywords, this graph understands that "Groundnut" is a *Crop*, "India" is a *Location*, and "Aflatoxin Contamination" is a *Trait/Issue*. It maps how these concepts relate to each other across decades of research.

### Key Features of this Pilot:
1. **AI-Driven Entity Extraction**: Extracted specific entities (Crops, Locations, Diseases, Breeding Methods) and their relationships directly from the text of 1,000 papers.
2. **Community Detection**: Used the Leiden algorithm to cluster related entities together into "Thematic Communities" (e.g., finding that Drought, Sorghum, and West Africa frequently appear together).
3. **AI Synthesis Reports**: Leveraged Google's `gemma-4-31b-it` model to automatically read the clusters and write high-level markdown reports summarizing the state of research for each community.
4. **Graph Database**: Compiled all findings into a queryable SQLite database and a JSON payload optimized for 3D web visualization.

---

## 📂 What's in this Repository?

To keep the repository lightweight, the massive raw data files (over 12,000 PDFs and raw JSON extractions) are deliberately excluded. This repository contains the code and the **finalized pilot data**.

### 1. The Pilot Data (`data/subset_1k/`)
*   `pilot_graph.db`: The finalized SQLite database. Contains all nodes, relationships, and the full AI-generated markdown reports for the 108 research communities.
*   `pilot_graph_export.json`: The compiled graph payload containing 14,659 nodes and 97,783 edges, formatted specifically for front-end 3D visualizers (like D3.js or 3d-force-graph).

### 2. The Code (`graph/`)
*   `entity_extractor.py`: The data mining script that reads raw paper text and extracts nodes/edges.
*   `community_detector.py`: Runs the Leiden algorithm to group the graph into clusters.
*   `community_summarizer.py`: Feeds the clusters to the Gemini LLM to generate the final research reports.
*   `build_graph.py`: The compilation script that stitches everything into the final `.db` and `.json` outputs.

### 3. Examples
*   `query_examples.py`: A Python script demonstrating how to write SQL queries against the `pilot_graph.db` to extract insights (e.g., finding the most connected crops, or pulling the largest community reports).
*   `examples_output.txt`: The output from running the query script.

---

## 🚀 Quick Start (Running the Examples)

You don't need to run the massive AI extraction pipeline to explore the data. You can query the finished database right away.

1. Ensure you have Python installed.
2. Run the example script:
   ```bash
   python3 query_examples.py
   ```
3. Look at `examples_output.txt` to see how the script successfully pulls the top AI-generated reports and maps the relationships around specific crops like "GROUNDNUT".

---

## 📊 Next Steps
The pilot study successfully validates the architecture. The next phase involves resuming the distributed extraction fleet to process the remaining ~11,000 papers in the ICRISAT library to build the global, production-ready Knowledge Graph.
