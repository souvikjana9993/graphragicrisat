import json
from collections import defaultdict
import networkx as nx
from pathlib import Path

def analyze_graph():
    graph_path = Path("data/graph_export.json")
    if not graph_path.exists():
        print("Graph JSON not found!")
        return

    with open(graph_path, "r") as f:
        data = json.load(f)

    # Build graph
    G = nx.Graph()
    for node in data["nodes"]:
        G.add_node(node["id"], type=node.get("type", "Unknown"))
    
    for link in data["links"]:
        G.add_edge(link["source"], link["target"])

    # Stats per node type
    type_stats = defaultdict(lambda: {"total": 0, "deg_0": 0, "deg_1": 0, "deg_2_plus": 0})
    
    for node, deg in G.degree():
        n_type = G.nodes[node]["type"]
        type_stats[n_type]["total"] += 1
        if deg == 0:
            type_stats[n_type]["deg_0"] += 1
        elif deg == 1:
            type_stats[n_type]["deg_1"] += 1
        else:
            type_stats[n_type]["deg_2_plus"] += 1

    print("=== Graph Degree Analysis ===")
    print(f"Total Nodes: {G.number_of_nodes()}")
    print(f"Total Edges: {G.number_of_edges()}")
    print("\nBreakdown by Node Type:")
    print(f"{'Node Type':<15} | {'Total':<6} | {'Deg 0':<6} | {'Deg 1':<6} | {'Deg 2+':<6}")
    print("-" * 50)
    
    for n_type, stats in sorted(type_stats.items()):
        print(f"{n_type:<15} | {stats['total']:<6} | {stats['deg_0']:<6} | {stats['deg_1']:<6} | {stats['deg_2_plus']:<6}")

if __name__ == "__main__":
    analyze_graph()
