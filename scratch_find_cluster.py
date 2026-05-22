"""Find ~100 related papers from our current graph based on shared connections."""
import json
from collections import defaultdict, Counter
from pathlib import Path

data = json.loads(Path("data/graph_export.json").read_text())

# Build adjacency from links
paper_neighbors = defaultdict(set)  # paper_id -> set of connected node ids
node_type = {}
node_name = {}

for n in data["nodes"]:
    node_type[n["id"]] = n.get("type", "")
    node_name[n["id"]] = n.get("display_name", n["id"])

for link in data["links"]:
    s, t = link["source"], link["target"]
    if node_type.get(s) == "Paper":
        paper_neighbors[s].add(t)
    if node_type.get(t) == "Paper":
        paper_neighbors[t].add(s)

paper_ids = [n["id"] for n in data["nodes"] if n.get("type") == "Paper"]
print(f"Total papers: {len(paper_ids)}")

# Find papers with most shared neighbors (most connected cluster)
# Score each pair of papers by shared non-paper neighbors
pair_scores = []
for i, p1 in enumerate(paper_ids):
    for p2 in paper_ids[i+1:]:
        shared = paper_neighbors[p1] & paper_neighbors[p2]
        # Only count non-paper shared nodes
        shared_non_paper = {s for s in shared if node_type.get(s) != "Paper"}
        if len(shared_non_paper) >= 3:
            pair_scores.append((p1, p2, len(shared_non_paper)))

pair_scores.sort(key=lambda x: -x[2])
print(f"\nTop 20 paper pairs by shared connections:")
for p1, p2, score in pair_scores[:20]:
    eid1 = p1.replace("paper_", "")
    eid2 = p2.replace("paper_", "")
    t1 = node_name.get(p1, "")[:50]
    t2 = node_name.get(p2, "")[:50]
    print(f"  {eid1} ↔ {eid2} ({score} shared) | {t1} | {t2}")

# Find the densest connected cluster of ~100 papers
# Greedy: start from the most connected paper, expand by most shared
paper_connectivity = Counter()
for p1, p2, score in pair_scores:
    paper_connectivity[p1] += score
    paper_connectivity[p2] += score

# Seed with top connected papers
seed_papers = [p for p, _ in paper_connectivity.most_common(10)]
cluster = set(seed_papers)

# Expand greedily
for p1, p2, score in pair_scores:
    if len(cluster) >= 100:
        break
    if p1 in cluster or p2 in cluster:
        cluster.add(p1)
        cluster.add(p2)

# If still < 100, add remaining by connectivity
if len(cluster) < 100:
    for p, _ in paper_connectivity.most_common():
        cluster.add(p)
        if len(cluster) >= 100:
            break

print(f"\n=== Selected cluster: {len(cluster)} papers ===")

# Analyze the cluster
cluster_crops = Counter()
cluster_topics = Counter()
for pid in cluster:
    for neighbor in paper_neighbors[pid]:
        nt = node_type.get(neighbor, "")
        nn = node_name.get(neighbor, "")
        if nt == "Crop":
            cluster_crops[nn] += 1
        elif nt == "Topic":
            cluster_topics[nn] += 1

print(f"\nCrops in cluster:")
for crop, count in cluster_crops.most_common(10):
    print(f"  {crop}: {count} papers")

print(f"\nTop topics in cluster:")
for topic, count in cluster_topics.most_common(15):
    print(f"  {topic}: {count} papers")

# Save the cluster paper IDs
eprint_ids = sorted([int(p.replace("paper_", "")) for p in cluster])
Path("data/test_cluster_ids.json").write_text(json.dumps(eprint_ids, indent=2))
print(f"\nSaved {len(eprint_ids)} paper IDs to data/test_cluster_ids.json")
print(f"IDs: {eprint_ids}")
