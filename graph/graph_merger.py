"""
Pandas-based Graph Merger (Microsoft GraphRAG style).
Reads all extracted subgraphs, converts to DataFrames, and merges entities with exact (NAME, TYPE) matches.
"""

import json
from pathlib import Path
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def load_extractions(input_dir: str):
    """Load all JSON extractions into flat lists."""
    entities = []
    relationships = []
    
    for file in Path(input_dir).glob("*.json"):
        if file.name == "extraction_progress.json":
            continue
            
        data = json.loads(file.read_text())
        entities.extend(data.get("entities", []))
        relationships.extend(data.get("relationships", []))
        
    return pd.DataFrame(entities), pd.DataFrame(relationships)

def merge_entities(entities_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge entities using Pandas groupby on exact UPPERCASE name and type.
    This exactly mirrors Microsoft GraphRAG's O(N) deduplication.
    """
    if entities_df.empty:
        return entities_df
        
    # Group by name and type
    merged = entities_df.groupby(["name", "type"], sort=False).agg(
        descriptions=("description", lambda x: list(set([d for d in x if d]))), # Deduplicate exact string descriptions
        source_ids=("source_id", list),
        frequency=("source_id", "count")
    ).reset_index()
    
    return merged

def merge_relationships(relationships_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge relationships that have the exact same source and target.
    """
    if relationships_df.empty:
        return relationships_df
        
    merged = relationships_df.groupby(["source", "target"], sort=False).agg(
        descriptions=("description", lambda x: list(set([d for d in x if d]))),
        source_ids=("source_id", list),
        weight_avg=("weight", lambda x: pd.to_numeric(x, errors='coerce').fillna(1.0).mean()),
        frequency=("source_id", "count")
    ).reset_index()
    
    merged["weight_avg"] = merged["weight_avg"].fillna(1.0)
    
    return merged

def run_merge(input_dir: str, output_file: str):
    log.info(f"Loading extractions from {input_dir}...")
    entities_df, relationships_df = load_extractions(input_dir)
    
    log.info(f"Loaded {len(entities_df)} raw entities and {len(relationships_df)} raw relationships.")
    
    merged_entities = merge_entities(entities_df)
    merged_rels = merge_relationships(relationships_df)
    
    log.info(f"Merged down to {len(merged_entities)} canonical entities and {len(merged_rels)} canonical relationships.")
    
    # Save to JSON for the summarizer step
    # We convert numpy types to standard python types for JSON serialization
    export_data = {
        "entities": merged_entities.to_dict(orient="records"),
        "relationships": merged_rels.to_dict(orient="records")
    }
    
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    Path(output_file).write_text(json.dumps(export_data, indent=2))
    log.info(f"Saved merged graph to {output_file}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=str, default="data/llm_extractions_v2")
    parser.add_argument("--output-file", type=str, default="data/merged_graph_v2.json")
    args = parser.parse_args()
    
    run_merge(args.input_dir, args.output_file)
