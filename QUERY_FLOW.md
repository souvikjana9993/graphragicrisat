# Trace: "Factors affecting sorghum yield"
This document traces exactly how the system processed the user's example query.

### 1. The Trigger
**User Query**: *"What are the factors affecting sorghum yield?"*
**Timestamp**: 2026-05-05 17:26:25

---

### 2. Backend Processing (`/api/query`)
- **Step 2.1: Context Retrieval**: 
  - The backend queries SQLite: `SELECT * FROM nodes WHERE type = 'Paper'`.
  - It finds **172 papers** in the current 100-paper test sample.
  - For each paper, it identifies its connected entities (e.g., Paper 123 is connected to `CROP: SORGHUM` and `TRAIT: DROUGHT TOLERANCE`).
- **Step 2.2: Context Assembly**: 
  - It compiles the "Cheat Sheet":
    ```text
    Paper 123 | Future Outlook... | Keywords: Arid Conditions, Rainfall | Crops: Sorghum | Abstract snippet...
    Paper 456 | Genetic diversity... | Keywords: QTL Mapping | Crops: Sorghum, Pearl Millet | Abstract snippet...
    ...
    ```
  - Total context size: ~15,000 tokens (well within the Gemma 4 31B window).

---

### 3. The LLM Reasoning (Gemma 4 31B)
The LLM reads the assembled context and performs three cognitive tasks:
1. **Filtering**: It ignores papers about "Chickpea" or "Groundnut" because they don't match the query.
2. **Synthesis**: It notices a pattern—many papers mention "Abiotic" vs "Biotic" factors. It decides to use these categories for the summary.
3. **Ranking**: It scores the papers based on how specifically they discuss "Yield Factors." 
   - *Result*: "Future Outlook..." gets **95%** because it explicitly lists rainfall and soil.
   - *Result*: "Aluminum tolerance" gets **80%** because it's a specific sub-factor.

---

### 4. The Response Generation
The LLM outputs a structured JSON object:
```json
{
  "explanation": "The identified papers cover a comprehensive range of factors...",
  "papers": [
    { "eprint_id": 123, "title": "Future Outlook...", "relevance_reason": "Discusses cultivation in arid conditions...", "score": 0.95 },
    ...
  ]
}
```

---

### 5. Frontend Visualization
- **Step 5.1: Rendering**: The UI receives the JSON and renders the "Explanation" box and the "Result Cards."
- **Step 5.2: Interaction**: You click on the "Future Outlook" card.
- **Step 5.3: Camera Flight**: The UI looks up `node_id: paper_123`, finds its $(x, y)$ position in the WebGL engine, and executes a smooth pan/zoom animation to that point.
- **Step 5.4: Details**: The side panel opens, pulling the full abstract and the **Community ID** for that paper.
