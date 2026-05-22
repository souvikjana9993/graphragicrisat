"""
Build the knowledge graph from scraped metadata and LLM extractions.

Reads metadata JSONs + LLM extraction JSONs → builds a NetworkX graph →
exports to SQLite + JSON for visualization.

Usage:
    python -m graph.build_graph
    python -m graph.build_graph --skip-llm  # skip LLM extraction step
"""

import argparse
import json
import logging
import sqlite3
import re
from collections import defaultdict
from pathlib import Path

import networkx as nx

from graph.node_matcher import NodeRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DATA_DIR = Path("data/raw_metadata")
CLUSTERED_GRAPH = Path("data/clustered_graph_v2.json")
CONCLUSIONS_DIR = Path("data/conclusions")
OUTPUT_DB = Path("data/graph.db")
OUTPUT_JSON = Path("data/graph_export.json")
COMMUNITY_REPORTS = Path("data/community_reports_v2.json")


def load_metadata(limit_extractions_dir: str = "") -> list[dict]:
    """Load all cleaned metadata JSONs."""
    files = sorted(DATA_DIR.glob("*.json"))
    # Skip raw files
    files = [f for f in files if "_raw" not in f.name]
    
    if limit_extractions_dir:
        extraction_files = {f.stem for f in Path(limit_extractions_dir).glob("*.json")}
        files = [f for f in files if f.stem in extraction_files]

    papers = []
    for f in files:
        try:
            papers.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            log.warning(f"Failed to parse {f.name}")
    return papers


def load_conclusion(eprint_id: int) -> str:
    """Load extracted conclusion for a paper."""
    f = CONCLUSIONS_DIR / f"{eprint_id}.txt"
    if f.exists():
        return f.read_text().strip()
    return ""


def build_graph(skip_llm: bool = False, limit_extractions_dir: str = "") -> tuple[nx.Graph, dict]:
    """
    Build the knowledge graph.

    Returns (networkx_graph, stats_dict).
    """
    papers = load_metadata(limit_extractions_dir)
    log.info(f"Loaded {len(papers)} papers")

    registry = NodeRegistry()
    G = nx.Graph()
    edges = []

    # Track which papers each author contributed to (for CO_AUTHORED edges)
    author_papers: dict[str, list[str]] = defaultdict(list)
    # Track paper features for RELATED_TO scoring
    paper_keywords: dict[str, set] = defaultdict(set)
    paper_crops: dict[str, set] = defaultdict(set)
    paper_topics: dict[str, set] = defaultdict(set)

    for paper in papers:
        eid = paper["eprint_id"]
        paper_node_id = f"paper_{eid}"

        conclusion = load_conclusion(eid)

        # ── Create Paper node ──
        G.add_node(paper_node_id, **{
            "id": paper_node_id,
            "type": "Paper",
            "eprint_id": eid,
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", "")[:500],  # truncate for viz
            "abstract_full": paper.get("abstract", ""),
            "conclusion": conclusion[:500] if conclusion else "",
            "date": paper.get("date", ""),
            "doi": paper.get("doi", ""),
            "publication": paper.get("publication", ""),
            "uri": paper.get("uri", f"https://oar.icrisat.org/{eid}/"),
            "display_name": paper.get("title", f"Paper {eid}"),
        })

        # ── Authors ──
        for author in paper.get("authors", []):
            given = author.get("given", "")
            family = author.get("family", "")
            if not family:
                continue

            author_id = registry.add_author(given, family)
            if author_id:
                edges.append(("AUTHORED_BY", paper_node_id, author_id))
                author_papers[author_id].append(paper_node_id)

        # ── Keywords (also try to extract crops from keywords) ──
        for kw in paper.get("keywords", []):
            kw_id = registry.add_keyword(kw)
            if kw_id:
                edges.append(("HAS_KEYWORD", paper_node_id, kw_id))
                paper_keywords[paper_node_id].add(kw_id)
            # Also check if this keyword is a crop name
            crop_id = registry.add_crop(kw)
            if crop_id:
                edges.append(("STUDIES_CROP", paper_node_id, crop_id))
                paper_crops[paper_node_id].add(crop_id)

        # ── Subjects / Crops (subject codes like s1.3) ──
        for subj in paper.get("subjects", []):
            crop_id = registry.add_crop(str(subj))
            if crop_id:
                edges.append(("STUDIES_CROP", paper_node_id, crop_id))
                paper_crops[paper_node_id].add(crop_id)

        # ── Also extract crops from agrotags (e.g., "groundnuts") ──
        for tag in paper.get("agrotags", []):
            crop_id = registry.add_crop(str(tag))
            if crop_id:
                edges.append(("STUDIES_CROP", paper_node_id, crop_id))
                paper_crops[paper_node_id].add(crop_id)

        # ── Agrotags / Topics ──
        for tag in paper.get("agrotags", []):
            topic_id = registry.add_topic(str(tag))
            if topic_id:
                edges.append(("COVERS_TOPIC", paper_node_id, topic_id))
                paper_topics[paper_node_id].add(topic_id)

        # ── Fishtags (also topics) ──
        for tag in paper.get("fishtags", []):
            topic_id = registry.add_topic(str(tag))
            if topic_id:
                edges.append(("COVERS_TOPIC", paper_node_id, topic_id))
                paper_topics[paper_node_id].add(topic_id)

        # ── Geotags / Locations ──
        for geo in paper.get("geotags", []):
            loc_id = registry.add_location(geo)
            if loc_id:
                edges.append(("LOCATED_IN", paper_node_id, loc_id))

        # ── Journal ──
        pub = paper.get("publication", "")
        if pub and pub != "UNSPECIFIED":
            journal_id = registry.add_journal(pub)
            if journal_id:
                edges.append(("PUBLISHED_IN", paper_node_id, journal_id))

        # ── Funders ──
        for funder in paper.get("funders", []):
            if funder and funder != "UNSPECIFIED":
                funder_id = registry.add_funder(funder)
                if funder_id:
                    edges.append(("FUNDED_BY", paper_node_id, funder_id))

    # ── Add all registered nodes to graph ──
    for node in registry.get_all_nodes():
        G.add_node(node["id"], **node)

    # ── Add all edges to graph ──
    for edge_type, source, target in edges:
        G.add_edge(source, target, type=edge_type)

    # ── Add LLM Subgraph (Microsoft GraphRAG nodes/edges) ──
    if not skip_llm and CLUSTERED_GRAPH.exists():
        log.info(f"Loading Microsoft GraphRAG clustered graph from {CLUSTERED_GRAPH}")
        cg = json.loads(CLUSTERED_GRAPH.read_text())
        
        # Add LLM Entities
        for ent in cg.get("entities", []):
            # Normalize ID
            ent_id = f"llm_{ent['name'].replace(' ', '_').upper()}"
            G.add_node(ent_id, **{
                "id": ent_id,
                "type": re.sub(r"[^A-Z_]", "", ent["type"].upper()) if ent["type"] else "CONCEPT",
                "display_name": ent["name"],
                "description": ent.get("canonical_description", ""),
                "community": ent.get("community", -1),
                "community_L1": ent.get("community_L1", -1),
                "frequency": ent.get("frequency", 1)
            })
            
            # Connect entity back to the papers it was extracted from
            for p_id in set(ent.get("source_ids", [])):
                G.add_edge(ent_id, p_id, type="MENTIONED_IN")
                
        # Add LLM Relationships (Entity-to-Entity)
        for rel in cg.get("relationships", []):
            s_id = f"llm_{rel['source'].replace(' ', '_').upper()}"
            t_id = f"llm_{rel['target'].replace(' ', '_').upper()}"
            
            if G.has_node(s_id) and G.has_node(t_id):
                G.add_edge(s_id, t_id, 
                           type="RELATES_TO", 
                           weight=rel.get("weight_avg", 1.0),
                           description=rel.get("canonical_description", ""),
                           community=rel.get("community", -1))


    # ── Derive CO_AUTHORED edges ──
    co_authored_count = 0
    seen_pairs = set()
    for author_id, paper_ids in author_papers.items():
        for other_author_id, other_paper_ids in author_papers.items():
            if author_id >= other_author_id:
                continue
            pair = (author_id, other_author_id)
            if pair in seen_pairs:
                continue
            shared = set(paper_ids) & set(other_paper_ids)
            if shared:
                G.add_edge(author_id, other_author_id,
                           type="CO_AUTHORED", shared_papers=len(shared))
                co_authored_count += 1
                seen_pairs.add(pair)

    # ── Derive RELATED_TO edges (paper similarity) ──
    related_count = 0
    paper_ids = [n for n, d in G.nodes(data=True) if d.get("type") == "Paper"]
    for i, p1 in enumerate(paper_ids):
        for p2 in paper_ids[i + 1:]:
            score = 0
            shared_kw = paper_keywords[p1] & paper_keywords[p2]
            shared_cr = paper_crops[p1] & paper_crops[p2]
            shared_tp = paper_topics[p1] & paper_topics[p2]

            score += len(shared_kw) * 2
            score += len(shared_cr) * 3
            score += len(shared_tp) * 1

            if score >= 4:
                G.add_edge(p1, p2, type="RELATED_TO", score=score)
                related_count += 1

    log.info(f"Derived edges: {co_authored_count} co-authored, {related_count} related-to")

    # ──────────────────────────────────────────────────────────────────────
    # NEW: GRAPH PRUNING (Level 2)
    # Remove entities that are "Islands" or "Dead Ends" to improve signal/noise.
    # ──────────────────────────────────────────────────────────────────────
    nodes_to_remove = []
    for node, degree in dict(G.degree()).items():
        ntype = G.nodes[node].get("type", "")
        # We always keep Paper nodes
        if ntype == "Paper":
            continue
        
        # Prune if the node is isolated (degree 0) or only connected to 1 thing (degree 1)
        if degree < 2:
            nodes_to_remove.append(node)
    
    log.info(f"Pruning: Removing {len(nodes_to_remove)} low-connectivity entity nodes (Degree < 2)")
    G.remove_nodes_from(nodes_to_remove)

    stats = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "papers": len(paper_ids),
        **{f"{k}_nodes": v for k, v in registry.get_stats().items()},
        "co_authored_edges": co_authored_count,
        "related_to_edges": related_count,
    }

    log.info(f"Graph post-pruning: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    log.info(f"Node breakdown: {json.dumps(registry.get_stats(), indent=2)}")

    return G, stats


def export_to_sqlite(G: nx.Graph, db_path: Path):
    """Export graph to SQLite for persistent storage."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # Create tables
    c.execute("DROP TABLE IF EXISTS nodes")
    c.execute("DROP TABLE IF EXISTS edges")
    c.execute("DROP TABLE IF EXISTS communities")

    c.execute("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            display_name TEXT,
            data TEXT  -- JSON blob for all properties
        )
    """)

    c.execute("""
        CREATE TABLE edges (
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            type TEXT NOT NULL,
            data TEXT,  -- JSON blob for edge properties
            FOREIGN KEY (source) REFERENCES nodes(id),
            FOREIGN KEY (target) REFERENCES nodes(id)
        )
    """)

    c.execute("""
        CREATE TABLE communities (
            id INTEGER PRIMARY KEY,
            title TEXT,
            report TEXT,
            node_count INTEGER
        )
    """)

    c.execute("CREATE INDEX idx_nodes_type ON nodes(type)")
    c.execute("CREATE INDEX idx_edges_source ON edges(source)")
    c.execute("CREATE INDEX idx_edges_target ON edges(target)")
    c.execute("CREATE INDEX idx_edges_type ON edges(type)")

    # Insert nodes
    for node_id, data in G.nodes(data=True):
        c.execute(
            "INSERT INTO nodes (id, type, display_name, data) VALUES (?, ?, ?, ?)",
            (node_id, data.get("type", ""), data.get("display_name", ""), json.dumps(data)),
        )

    # Insert edges
    for source, target, data in G.edges(data=True):
        c.execute(
            "INSERT INTO edges (source, target, type, data) VALUES (?, ?, ?, ?)",
            (source, target, data.get("type", ""), json.dumps(data)),
        )

    # Insert community reports
    if COMMUNITY_REPORTS.exists():
        log.info(f"Loading community reports from {COMMUNITY_REPORTS}")
        reports = json.loads(COMMUNITY_REPORTS.read_text())
        for cid_str, report in reports.items():
            c.execute(
                "INSERT INTO communities (id, title, report, node_count) VALUES (?, ?, ?, ?)",
                (int(cid_str), report["title"], report["report_markdown"], report["node_count"])
            )

    conn.commit()
    conn.close()
    log.info(f"Exported to SQLite: {db_path}")


def export_to_json(G: nx.Graph, json_path: Path):
    """Export graph to JSON for D3.js visualization."""
    json_path.parent.mkdir(parents=True, exist_ok=True)

    nodes = []
    for node_id, data in G.nodes(data=True):
        node = {**data}
        node["id"] = node_id
        node["degree"] = G.degree(node_id)
        # Remove heavy fields for viz
        node.pop("abstract_full", None)
        nodes.append(node)

    links = []
    for source, target, data in G.edges(data=True):
        links.append({
            "source": source,
            "target": target,
            "type": data.get("type", ""),
            **{k: v for k, v in data.items() if k != "type"},
        })

    export = {
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
        },
    }

    json_path.write_text(json.dumps(export, indent=2, ensure_ascii=False))
    log.info(f"Exported to JSON: {json_path} ({len(nodes)} nodes, {len(links)} links)")


def main():
    parser = argparse.ArgumentParser(description="Build ICRISAT knowledge graph")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM extraction data")
    parser.add_argument("--data-dir", type=str, default="data/raw_metadata")
    parser.add_argument("--clustered-graph", type=str, default="data/clustered_graph_v2.json")
    parser.add_argument("--community-reports", type=str, default="data/community_reports_v2.json")
    parser.add_argument("--output-db", type=str, default="data/graph.db")
    parser.add_argument("--output-json", type=str, default="data/graph_export.json")
    parser.add_argument("--limit-extractions", type=str, default="")
    args = parser.parse_args()

    global DATA_DIR, CLUSTERED_GRAPH, OUTPUT_DB, OUTPUT_JSON, COMMUNITY_REPORTS
    DATA_DIR = Path(args.data_dir)
    CLUSTERED_GRAPH = Path(args.clustered_graph)
    COMMUNITY_REPORTS = Path(args.community_reports)
    OUTPUT_DB = Path(args.output_db)
    OUTPUT_JSON = Path(args.output_json)

    G, stats = build_graph(skip_llm=args.skip_llm, limit_extractions_dir=args.limit_extractions)

    export_to_sqlite(G, OUTPUT_DB)
    export_to_json(G, OUTPUT_JSON)

    # Also save stats
    stats_path = OUTPUT_JSON.parent / "graph_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2))
    log.info(f"Stats saved to {stats_path}")


if __name__ == "__main__":
    main()
