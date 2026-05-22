"""
LLM-powered entity and relationship extraction from paper abstracts using Gemma 4 27B.
Uses the Microsoft GraphRAG tuple-based extraction method.

Usage:
    python -m graph.entity_extractor --data-dir data/raw_metadata --output-dir data/llm_extractions_v2 --test-cluster
"""

import argparse
import json
import logging
import os
import time
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from google import genai

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

EXTRACTION_PROMPT = """
-Goal-
Given a research abstract from ICRISAT, identify all entities of specific types and all relationships among them.

-Steps-
1. Identify all entities. Extract:
- entity_name: Name of the entity, CAPITALIZED (e.g. GROUNDNUT, QTL MAPPING, DROUGHT TOLERANCE). Always use the most common English scientific/agricultural name.
- entity_type: One of: CROP, TRAIT, METHOD, GENE_MARKER, CONDITION, ORGANISM, CONCEPT, LOCATION
  **CRITICAL:** You MUST select from the exact types above. DO NOT invent new types (e.g., do not use "PEST" or "CHICKPEA"). DO NOT wrap the type in angle brackets (e.g., use METHOD, not <METHOD>).
- entity_description: Comprehensive description of the entity's attributes in this context.
Format each entity EXACTLY as: ("entity"|<entity_name>|<entity_type>|<entity_description>)

2. Identify relationships between the entities you found.
Format each relationship EXACTLY as: ("relationship"|<source_entity_name>|<target_entity_name>|<relationship_description>|<relationship_strength>)
where <relationship_strength> is a numeric score from 1 to 10 indicating how strongly they are related.

Return output as a single list of these tuples. Use ## as the delimiter between tuples. Do not include any markdown blocks, json, or conversational text.

Title: {title}
Abstract: {abstract}
"""


class EntityExtractor:
    """Extract entity/relationship subgraphs from abstracts using Gemma."""

    def __init__(self, api_key: str, model_name: str = "gemma-4-31b-it"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.request_count = 0
        self.delay_seconds = 2.0  # rate limit

    def _rate_limit(self):
        """Simple rate limiting."""
        self.request_count += 1
        if self.request_count > 1:
            time.sleep(self.delay_seconds)

    def extract_graph(self, title: str, abstract: str, paper_id: str) -> dict | None:
        """Extract entities and relationships from a single paper."""
        if not abstract or len(abstract.strip()) < 50:
            log.warning(f"Abstract too short or empty for: {title[:50]}")
            return None

        prompt = EXTRACTION_PROMPT.format(title=title, abstract=abstract)

        self._rate_limit()

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={
                    "temperature": 0.1,  # low temp for factual extraction
                },
            )
            
            raw_text = response.text.strip()
            
            entities = []
            relationships = []

            records = [r.strip() for r in raw_text.split("##")]
            for raw_record in records:
                # Clean up outer parens
                record = re.sub(r"^\(|\)$", "", raw_record.strip())
                if not record:
                    continue
                
                attributes = record.split("|")
                record_type = attributes[0].strip().replace('"', '')
                
                if record_type == "entity" and len(attributes) >= 4:
                    raw_type = attributes[2].strip().upper()
                    # Strip angle brackets if LLM hallucinates them
                    clean_type = re.sub(r"[<>]", "", raw_type)
                    
                    # Fallback for hallucinated types
                    allowed_types = {"CROP", "TRAIT", "METHOD", "GENE_MARKER", "CONDITION", "ORGANISM", "CONCEPT", "LOCATION"}
                    if clean_type not in allowed_types:
                        clean_type = "CONCEPT"
                        
                    entities.append({
                        "name": attributes[1].strip().upper(),
                        "type": clean_type,
                        "description": attributes[3].strip(),
                        "source_id": paper_id
                    })
                elif record_type == "relationship" and len(attributes) >= 5:
                    relationships.append({
                        "source": attributes[1].strip().upper(),
                        "target": attributes[2].strip().upper(),
                        "description": attributes[3].strip(),
                        "weight": attributes[4].strip(),
                        "source_id": paper_id
                    })

            return {"entities": entities, "relationships": relationships}

        except Exception as e:
            log.error(f"LLM extraction failed for '{title[:50]}': {e}")
            return None


def run_extraction(file_list: list, output_dir: str, api_key: str):
    """Run entity extraction on a provided list of metadata files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    completed = set([f.stem for f in output_path.glob("*.json")])
    extractor = EntityExtractor(api_key=api_key)

    log.info(f"Processing {len(file_list)} files in this worker's partition.")

    for i, mf in enumerate(file_list):
        eprint_id = mf.stem
        output_file = output_path / f"{eprint_id}.json"
        
        # IDEMPOTENCY: Check progress file OR physical file presence
        if eprint_id in completed or output_file.exists():
            if i % 100 == 0:
                log.info(f"[{i+1}/{len(metadata_files)}] Skipping already extracted ID {eprint_id}")
            continue

        metadata = json.loads(mf.read_text())
        title = metadata.get("title", "")
        abstract = metadata.get("abstract", "")

        if not abstract:
            log.info(f"ID {eprint_id}: No abstract — skipping LLM extraction")
            completed.add(eprint_id)
            continue

        log.info(f"Extracting graph from ID {eprint_id}: {title[:60]}...")
        graph_data = extractor.extract_graph(title, abstract, f"paper_{eprint_id}")

        if graph_data:
            output_file = output_path / f"{eprint_id}.json"
            output_file.write_text(
                json.dumps(graph_data, indent=2, ensure_ascii=False)
            )
            log.info(f"  → {len(graph_data['entities'])} entities, {len(graph_data['relationships'])} relationships")

        completed.add(eprint_id)

        completed.add(eprint_id)
        
        # RATE LIMIT SAFETY: Mandatory cooldown between papers
        time.sleep(5)

    log.info(f"Batch complete. {len(completed)} total papers handled by this worker.")


def main():
    parser = argparse.ArgumentParser(description="Extract entities from papers")
    parser.add_argument("--data-dir", type=str, default="data/raw_metadata")
    parser.add_argument("--output-dir", type=str, default="data/llm_extractions_v2")
    parser.add_argument("--test-cluster", action="store_true")
    parser.add_argument("--worker-id", type=int, default=0, help="ID of this worker (0 to total-1)")
    parser.add_argument("--total-workers", type=int, default=1, help="Total number of workers running")
    args = parser.parse_args()

    API_KEY = os.environ.get("GOOGLE_API_KEY")
    if not API_KEY:
        log.error("GOOGLE_API_KEY not found.")
        return

    # CONTINUOUS LOOP: Keep processing as long as the scraper is running
    while True:
        log.info(f"Scanning for new metadata files (Worker {args.worker_id}/{args.total_workers})...")
        metadata_files = sorted(Path(args.data_dir).glob("*.json"))
        metadata_files = [f for f in metadata_files if "_raw" not in f.name]
        
        # PARTITIONING: Only take papers assigned to this worker
        if args.total_workers > 1:
            # We use the hash of the filename to ensure even distribution
            import hashlib
            metadata_files = [
                f for f in metadata_files 
                if int(hashlib.md5(f.stem.encode()).hexdigest(), 16) % args.total_workers == args.worker_id
            ]

        # Determine how many are truly new
        output_path = Path(args.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        existing_extractions = set(f.stem for f in output_path.glob("*.json"))
        to_process = [f for f in metadata_files if f.stem not in existing_extractions]

        if args.test_cluster:
            test_cluster_file = Path("data/test_cluster_ids.json")
            if test_cluster_file.exists():
                cluster_ids = set([str(x) for x in json.loads(test_cluster_file.read_text())])
                metadata_files = [f for f in metadata_files if f.stem in cluster_ids]
            else:
                log.warning("Test cluster file not found.")

        if not to_process:
            log.info("No new files to process for this worker's partition. Waiting 60s...")
            time.sleep(60)
            continue

        run_extraction(to_process, args.output_dir, API_KEY)
        
        # Be polite to the OS
        time.sleep(5)


if __name__ == "__main__":
    main()
