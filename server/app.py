"""
FastAPI backend serving the graph data and LLM query interface.

Usage:
    uvicorn server.app:app --reload --port 8000
"""

import json
import logging
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv() # Load GOOGLE_API_KEY from .env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import google.genai.errors

# Retry decorator for all LLM calls
llm_retry = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type(google.genai.errors.ClientError),
    reraise=True
)

app = FastAPI(title="ICRISAT GraphRAG", version="1.0")

# CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path("data/graph.db")
JSON_PATH = Path("data/graph_export.json")
METADATA_DIR = Path("data/raw_metadata")
EXTRACTIONS_DIR = Path("data/llm_extractions_v2")

# Robustness check: Ensure critical directories exist
def validate_environment():
    required_dirs = [METADATA_DIR, EXTRACTIONS_DIR, Path("data")]
    for d in required_dirs:
        if not d.exists():
            log.warning(f"Required directory missing: {d}. Creating it...")
            d.mkdir(parents=True, exist_ok=True)
    
    if not DB_PATH.exists():
        log.error(f"DATABASE MISSING: {DB_PATH}. GraphRAG will be limited to Naive mode.")

validate_environment()

# LLM client (lazy init)
_llm_client = None
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MODEL_NAME = "gemma-4-31b-it"


def get_llm_client():
    global _llm_client
    if _llm_client is None:
        key = API_KEY
        if not key:
            raise HTTPException(500, "GOOGLE_API_KEY not set")
        _llm_client = genai.Client(api_key=key)
    return _llm_client


def get_db():
    """Get a SQLite connection."""
    if not DB_PATH.exists():
        raise HTTPException(500, f"Database not found at {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────────────────────────────
# Graph data endpoints
# ──────────────────────────────────────────────────────────────────────

@app.get("/api/graph")
def get_graph():
    """Return the full graph JSON for D3.js visualization."""
    if not JSON_PATH.exists():
        raise HTTPException(404, "Graph export not found. Run build_graph.py first.")
    return json.loads(JSON_PATH.read_text())


@app.get("/api/stats")
def get_stats():
    """Return graph statistics."""
    stats_path = Path("data/graph_stats.json")
    if stats_path.exists():
        return json.loads(stats_path.read_text())
    return {"error": "Stats not generated yet"}


@app.get("/api/paper/{eprint_id}")
def get_paper(eprint_id: int):
    """Get full paper details."""
    metadata_file = METADATA_DIR / f"{eprint_id}.json"
    if not metadata_file.exists():
        raise HTTPException(404, f"Paper {eprint_id} not found")

    paper = json.loads(metadata_file.read_text())

    # Also load LLM extraction if available
    llm_file = Path("data/llm_extractions") / f"{eprint_id}.json"
    if llm_file.exists():
        paper["llm_entities"] = json.loads(llm_file.read_text())

    return paper


@app.get("/api/search")
def search_nodes(q: str = Query(..., min_length=1), limit: int = 20):
    """Search nodes by display name (fuzzy text search)."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "SELECT id, type, display_name, data FROM nodes WHERE LOWER(display_name) LIKE ? LIMIT ?",
            (f"%{q.lower()}%", limit),
        )
        results = []
        for row in cursor:
            data = json.loads(row["data"])
            results.append({
                "id": row["id"],
                "type": row["type"],
                "display_name": row["display_name"],
                "data": data,
            })
        return {"query": q, "count": len(results), "results": results}
    finally:
        conn.close()


@app.get("/api/neighbors/{node_id}")
def get_neighbors(node_id: str, hops: int = 1):
    """Get the N-hop neighborhood of a node."""
    conn = get_db()
    try:
        # Verify node exists
        node_row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not node_row:
            raise HTTPException(404, f"Node {node_id} not found")

        # BFS to collect N-hop neighborhood
        visited_nodes = {node_id}
        frontier = {node_id}
        all_edges = []

        for hop in range(hops):
            next_frontier = set()
            for current in frontier:
                # Get outgoing edges
                cursor = conn.execute(
                    "SELECT source, target, type, data FROM edges WHERE source = ? OR target = ?",
                    (current, current),
                )
                for row in cursor:
                    edge = {
                        "source": row["source"],
                        "target": row["target"],
                        "type": row["type"],
                    }
                    all_edges.append(edge)
                    neighbor = row["target"] if row["source"] == current else row["source"]
                    if neighbor not in visited_nodes:
                        next_frontier.add(neighbor)
                        visited_nodes.add(neighbor)
            frontier = next_frontier

        # Fetch node data for all visited nodes
        nodes = []
        for nid in visited_nodes:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
            if row:
                data = json.loads(row["data"])
                nodes.append({
                    "id": row["id"],
                    "type": row["type"],
                    "display_name": row["display_name"],
                    **data,
                })

        # Deduplicate edges
        seen_edges = set()
        unique_edges = []
        for e in all_edges:
            key = (e["source"], e["target"], e["type"])
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        return {
            "center_node": node_id,
            "hops": hops,
            "nodes": nodes,
            "links": unique_edges,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# LLM Query endpoint
# ──────────────────────────────────────────────────────────────────────

from enum import Enum

class QueryMode(str, Enum):
    NAIVE = "naive"
    LOCAL = "local"
    GLOBAL = "global"
    DRIFT = "drift"

class QueryRequest(BaseModel):
    query: str
    mode: str = "naive"
    max_results: int = 10
    hops: int = 2


class PaperResult(BaseModel):
    eprint_id: int
    title: str
    relevance_reason: str
    score: float


class QueryResponse(BaseModel):
    papers: list[PaperResult]
    explanation: str


QUERY_PROMPT = """You are an expert agricultural research assistant with access to a knowledge graph
of ICRISAT research papers. Given the user's query, identify the most relevant papers
from the database below.

USER QUERY: {query}

AVAILABLE PAPERS (ID | Title | Keywords | Crop | Abstract snippet):
{papers_context}

Return your answer ONLY as a raw JSON object with the following schema:
{{
  "papers": [
    {{
      "eprint_id": 123,
      "title": "Paper title",
      "relevance_reason": "Brief explanation of relevance",
      "score": 0.85
    }}
  ],
  "explanation": "Overall explanation of what was found"
}}
Do not include markdown blocks or any other text outside the JSON.
Score each paper from 0.0 to 1.0 based on relevance.
"""


@app.post("/api/query")
async def query_papers(req: QueryRequest):
    """LLM-powered search with multiple modes (Naive, Local, Global, Drift)."""
    if req.mode == QueryMode.GLOBAL:
        return await query_global(req)
    elif req.mode == QueryMode.LOCAL:
        return await query_local(req)
    elif req.mode == QueryMode.DRIFT:
        return await query_drift(req)
    else:
        return await query_naive(req)

async def query_local(req: QueryRequest):
    """Reason about specific entities and their immediate graph neighborhood (Ranked)."""
    return await _query_graph_walk(req, hops=req.hops)

async def query_drift(req: QueryRequest):
    """
    DRIFT Search: Performs a multi-hop graph walk (Breadth-First) 
    to find non-obvious connections across papers.
    """
    return await _query_graph_walk(req, hops=req.hops)

@llm_retry
async def _query_graph_walk(req: QueryRequest, hops: int = 1):
    conn = get_db()
    try:
        log.info(f"{req.mode.upper()} Query: {req.query}")
        # 1. Find anchor entities
        keywords = [k for k in req.query.split() if len(k) > 3]
        match_cursor = conn.execute(
            "SELECT id, display_name, type, data FROM nodes WHERE display_name LIKE ? LIMIT 3", 
            (f"%{keywords[0]}%",)
        )
        anchors = match_cursor.fetchall()
        
        if not anchors:
            return await query_naive(req)
            
        # 2. Perform N-hop walk with weight ranking
        context_parts = []
        seen_nodes = set()
        
        current_hop_nodes = [a["id"] for a in anchors]
        for h in range(hops):
            next_hop_nodes = []
            for node_id in current_hop_nodes:
                if node_id in seen_nodes: continue
                seen_nodes.add(node_id)
                
                # Fetch node info
                node_row = conn.execute("SELECT display_name, type, data FROM nodes WHERE id = ?", (node_id,)).fetchone()
                if not node_row: continue
                
                ndata = json.loads(node_row["data"])
                context_parts.append(f"[{h}-HOP ENTITY]: {node_row['display_name']} ({node_row['type']})\nDESCRIPTION: {ndata.get('description', '')}")
                
                # Fetch top neighbors by edge weight (RANKING FIX)
                neighbors = conn.execute("""
                    SELECT n.id, n.display_name, n.type, e.data as edge_data 
                    FROM edges e JOIN nodes n ON (CASE WHEN e.source = ? THEN e.target ELSE e.source END = n.id)
                    WHERE (e.source = ? OR e.target = ?)
                    ORDER BY CAST(json_extract(e.data, '$.weight') AS FLOAT) DESC
                    LIMIT 15
                """, (node_id, node_id, node_id)).fetchall()
                
                for nb in neighbors:
                    edata = json.loads(nb["edge_data"])
                    context_parts.append(f"- RELATES TO {nb['display_name']} (Weight: {edata.get('weight', 1)}): {edata.get('description', '')}")
                    next_hop_nodes.append(nb["id"])
            
            current_hop_nodes = next_hop_nodes[:10] # limit expansion to avoid context overflow

        prompt = f"""You are an ICRISAT research assistant. Use the following {hops}-hop Graph Context to answer the question.
Focus on how the entities are connected across different papers.

# GRAPH CONTEXT
{"\n".join(context_parts[:50])}

# USER QUESTION
{req.query}

Return a JSON response: {{"explanation": "...", "papers": []}}
"""
        client = get_llm_client()
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = response.text.strip()
        if "```json" in text: text = text.split("```json")[1].split("```")[0]
        elif "```" in text: text = text.split("```")[1].split("```")[0]
        return json.loads(text)
    finally:
        conn.close()

@llm_retry
async def query_global(req: QueryRequest):
    """Reason about the whole database using Hierarchical Community Reports."""
    conn = get_db()
    try:
        log.info(f"Global Query: {req.query}")
        # Fetch high-level (L0) and detailed (L1) reports
        cursor = conn.execute("SELECT title, report, node_count FROM communities ORDER BY node_count DESC LIMIT 20")
        reports = cursor.fetchall()
        
        if not reports:
            return {"explanation": "No community reports found.", "papers": []}
            
        # Segment into broad and specific context
        broad_reports = [r for r in reports if r["node_count"] > 20]
        specific_reports = [r for r in reports if r["node_count"] <= 20]
        
        context = "### BROAD THEMES\n" + "\n".join([f"- {r['title']}: {r['report'][:500]}..." for r in broad_reports])
        context += "\n\n### SPECIFIC FINDINGS\n" + "\n".join([f"- {r['title']}: {r['report']}" for r in specific_reports[:10]])
        
        prompt = f"""You are an ICRISAT research director. Use these Hierarchical Community Reports to answer.
        
# CONTEXT
{context}

# USER QUESTION
{req.query}

Return a JSON response: {{"explanation": "...", "papers": []}}
"""
        client = get_llm_client()
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = response.text.strip()
        if "```json" in text: text = text.split("```json")[1].split("```")[0]
        elif "```" in text: text = text.split("```")[1].split("```")[0]
        return json.loads(text)
    finally:
        conn.close()

@llm_retry
async def query_naive(req: QueryRequest):
    """Original paper-centric search (Naive RAG)."""
    conn = get_db()
    try:
        log.info(f"Naive Query: {req.query}")
        
        # Build context from all papers
        cursor = conn.execute(
            "SELECT id, display_name, data FROM nodes WHERE type = 'Paper'"
        )
        papers_context_lines = []
        paper_lookup = {}

        all_paper_rows = cursor.fetchall()
        log.info(f"Retrieved {len(all_paper_rows)} papers for context building.")

        for row in all_paper_rows:
            data = json.loads(row["data"])
            eid = data.get("eprint_id", "")
            title = data.get("title", "")
            abstract_snippet = data.get("abstract", "")[:200]

            # Get connected keywords and crops
            edge_cursor = conn.execute(
                """SELECT n.display_name, n.type, e.type as edge_type
                   FROM edges e JOIN nodes n ON (
                       CASE WHEN e.source = ? THEN e.target ELSE e.source END = n.id
                   )
                   WHERE (e.source = ? OR e.target = ?)
                   AND n.type IN ('Keyword', 'Crop', 'Topic', 'CROP', 'TRAIT', 'METHOD', 'GENE_MARKER')""",
                (row["id"], row["id"], row["id"]),
            )
            keywords = []
            crops = []
            for erow in edge_cursor:
                if erow["type"] in ["Crop", "CROP"]:
                    crops.append(erow["display_name"])
                else:
                    keywords.append(erow["display_name"])

            line = f"{eid} | {title} | Keywords: {', '.join(keywords[:5])} | Crops: {', '.join(crops)} | {abstract_snippet}"
            papers_context_lines.append(line)
            paper_lookup[str(eid)] = {"eprint_id": eid, "title": title}

        log.info(f"Context built: {len(papers_context_lines)} total lines.")
        
        prompt = QUERY_PROMPT.format(
            query=req.query,
            papers_context="\n".join(papers_context_lines[:200]),  # cap context
        )

        log.info("Sending request to Gemma 4 31B...")
        client = get_llm_client()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config={
                "temperature": 0.3,
            },
        )
        log.info("LLM response received.")

        # Clean up potential markdown formatting from response
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result = QueryResponse.model_validate_json(text)
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Query failed: {str(e)}")
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Static file serving (visualization)
# ──────────────────────────────────────────────────────────────────────

VIZ_DIR = Path("viz")
if VIZ_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(VIZ_DIR)), name="static")


@app.get("/")
def serve_index():
    """Serve the main visualization page."""
    index_path = VIZ_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "ICRISAT GraphRAG API. Visualization not built yet."}
