import json
from collections import defaultdict

def analyze_communities():
    with open('data/clustered_graph_v2.json', 'r') as f:
        data = json.load(f)
    
    entities = data.get('entities', [])
    
    # Group entities by community
    comm_groups = defaultdict(list)
    for ent in entities:
        comm_groups[ent['community']].append(ent['name'])
    
    # Sort communities by size
    sorted_comms = sorted(comm_groups.items(), key=lambda x: len(x[1]), reverse=True)
    
    print("--- PRELIMINARY CLUSTER ANALYSIS ---")
    print(f"Total Nodes: {len(entities)}")
    print(f"Total Communities: {len(sorted_comms)}")
    print("\nTop 5 Largest Communities:")
    
    for i in range(min(5, len(sorted_comms))):
        cid, members = sorted_comms[i]
        print(f"\n[Community {cid}] ({len(members)} nodes)")
        # Show first 15 members
        print(", ".join(members[:15]) + ("..." if len(members) > 15 else ""))

if __name__ == "__main__":
    analyze_communities()
