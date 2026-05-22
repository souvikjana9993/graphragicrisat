import json

def remove_nans(obj):
    if isinstance(obj, float):
        if obj != obj: # is NaN
            return 1.0
    elif isinstance(obj, dict):
        return {k: remove_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [remove_nans(v) for v in obj]
    return obj

for file in ["data/clustered_graph_v2.json", "data/graph_export.json"]:
    with open(file, "r") as f:
        content = f.read()
    # Replace the NaN tokens with 1.0 to make it parseable
    content = content.replace("NaN", "1.0")
    
    # Verify it parses now
    obj = json.loads(content)
    
    with open(file, "w") as f:
        json.dump(obj, f, indent=2)
    print(f"Fixed {file}")
