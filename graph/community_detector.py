"""
Hierarchical Leiden Community Detection (Microsoft GraphRAG style).
Reads the summarized graph, runs Leiden on the relationships, and assigns Level 0, 1, and 2 community IDs to each entity.
"""

import json
import logging
from pathlib import Path
import pandas as pd
import igraph as ig
import leidenalg as la

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def build_igraph(entities, relationships):
    """Build an igraph object from entities and relationships."""
    # Create mapping of entity name to index
    name_to_id = {e["name"]: i for i, e in enumerate(entities)}
    
    # Filter relationships to only those where both source and target exist
    valid_edges = []
    weights = []
    
    for r in relationships:
        s = r["source"]
        t = r["target"]
        if s in name_to_id and t in name_to_id:
            valid_edges.append((name_to_id[s], name_to_id[t]))
            # Use weight if available, else 1.0
            try:
                w = float(r.get("weight", 1.0))
            except (ValueError, TypeError):
                w = 1.0
            weights.append(w)
            
    # Create graph
    g = ig.Graph(n=len(entities), edges=valid_edges, directed=False)
    g.es["weight"] = weights
    
    # Add vertex attributes
    g.vs["name"] = [e["name"] for e in entities]
    
    return g, name_to_id

def run_leiden_hierarchical(g: ig.Graph):
    """Run hierarchical Leiden clustering and return community mappings."""
    log.info(f"Running Leiden clustering on graph with {g.vcount()} nodes and {g.ecount()} edges...")
    
    # We use ModularityVertexPartition for undirected weighted graphs
    # To simulate hierarchy, we could run it multiple times with different resolution parameters,
    # or just use the find_partition method.
    # Microsoft uses a custom recursive wrapper, but we can approximate it cleanly.
    
    # Level 0: Global Communities (Resolution = 1.0)
    partition_l0 = la.find_partition(g, la.ModularityVertexPartition, weights="weight", n_iterations=2)
    
    # Level 1: Sub-communities (Higher resolution = more, smaller communities)
    partition_l1 = la.find_partition(g, la.CPMVertexPartition, weights="weight", resolution_parameter=0.5, n_iterations=2)
    
    # Extract mappings
    mapping = {}
    for v in g.vs:
        mapping[v["name"]] = {
            "community_L0": partition_l0.membership[v.index],
            "community_L1": partition_l1.membership[v.index]
        }
        
    return mapping

def run_community_detection(input_file: str, output_file: str):
    log.info(f"Loading summarized graph from {input_file}...")
    data = json.loads(Path(input_file).read_text())
    
    entities = data.get("entities", [])
    relationships = data.get("relationships", [])
    
    if not entities or not relationships:
        log.warning("Empty graph. Skipping clustering.")
        return
        
    g, name_to_id = build_igraph(entities, relationships)
    
    # Simplify graph (remove multi-edges and self-loops, combine weights)
    g.simplify(combine_edges=dict(weight="sum"))
    
    community_map = run_leiden_hierarchical(g)
    
    # Assign communities back to entities
    for e in entities:
        if e["name"] in community_map:
            e["community"] = community_map[e["name"]]["community_L0"]
            e["community_L1"] = community_map[e["name"]]["community_L1"]
        else:
            e["community"] = -1
            e["community_L1"] = -1
            
    # Add communities to relationships (for edge coloring if needed)
    for r in relationships:
        s_com = community_map.get(r["source"], {}).get("community_L0", -1)
        t_com = community_map.get(r["target"], {}).get("community_L0", -1)
        # An edge belongs to a community if both endpoints are in it, else it's a cross-community edge
        if s_com == t_com:
            r["community"] = s_com
        else:
            r["community"] = -1
            
    export_data = {
        "entities": entities,
        "relationships": relationships
    }
    
    Path(output_file).write_text(json.dumps(export_data, indent=2))
    log.info(f"Saved clustered graph to {output_file}")
    
    # Log some stats
    l0_count = len(set([e["community"] for e in entities]))
    l1_count = len(set([e["community_L1"] for e in entities]))
    log.info(f"Found {l0_count} Level-0 communities and {l1_count} Level-1 communities.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", type=str, default="data/summarized_graph_v2.json")
    parser.add_argument("--output-file", type=str, default="data/clustered_graph_v2.json")
    args = parser.parse_args()
    
    run_community_detection(args.input_file, args.output_file)
