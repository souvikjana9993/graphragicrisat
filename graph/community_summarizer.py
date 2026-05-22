import json
import logging
import os
import time
from pathlib import Path
from google import genai
import google.genai.errors
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

COMMUNITY_REPORT_PROMPT = """
You are a senior scientific research director at ICRISAT. You are provided with a collection of entities and relationships that belong to a specific "Community" or "Thematic Cluster" within our research knowledge graph.

Your task is to write a comprehensive "Community Report" that synthesizes this information into a high-level summary for stakeholders.

# INPUT DATA
## Entities in this Community:
{entities}

## Relationships in this Community:
{relationships}

# INSTRUCTIONS
1. **Title**: Create a concise, professional title for this community (e.g., "Genomics of Drought Tolerance in Pearl Millet").
2. **Executive Summary**: Provide a 2-3 sentence overview of the core research theme.
3. **Key Findings**: List 3-5 major scientific findings or focus areas identified in this cluster.
4. **Key Entities**: Mention the most important crops, traits, or genes involved.
5. **Open Questions/Gaps**: Identify any missing information or potential future research directions mentioned.

Return the report in **Markdown format**. Be scientific, authoritative, and objective.
"""

class CommunitySummarizer:
    def __init__(self, api_key: str, model_name: str = "models/gemma-4-31b-it"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=1, min=5, max=120),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def summarize_community(self, community_id: int, entities: list, relationships: list) -> str:
        # Prepare text representation
        entity_text = "\n".join([f"- {e['name']} ({e['type']}): {e.get('canonical_description', '')}" for e in entities[:30]])
        rel_text = "\n".join([f"- {r['source']} -> {r['target']}: {r.get('description', '')}" for r in relationships[:20]])

        prompt = COMMUNITY_REPORT_PROMPT.format(
            entities=entity_text,
            relationships=rel_text
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config={"temperature": 0.2}
        )
        return response.text.strip()

def run_community_summarization(input_file: str, output_file: str, api_key: str):
    log.info(f"Loading clustered graph from {input_file}...")
    data = json.loads(Path(input_file).read_text())
    
    entities = data.get("entities", [])
    relationships = data.get("relationships", [])
    
    # Group by community
    community_nodes = {}
    for ent in entities:
        cid = ent.get("community", -1)
        if cid == -1: continue
        if cid not in community_nodes: community_nodes[cid] = []
        community_nodes[cid].append(ent)
    
    # Filter for meaningful communities (size > 3)
    active_communities = {cid: nodes for cid, nodes in community_nodes.items() if len(nodes) >= 3}
    log.info(f"Identified {len(active_communities)} meaningful communities for summarization.")

    # Relationships grouping (approximate)
    community_rels = {}
    for rel in relationships:
        # Find which community the source/target belong to
        # (This is a simplified mapping)
        src_name = rel['source']
        src_node = next((e for e in entities if e['name'] == src_name), None)
        if src_node:
            cid = src_node.get('community', -1)
            if cid != -1:
                if cid not in community_rels: community_rels[cid] = []
                community_rels[cid].append(rel)

    summarizer = CommunitySummarizer(api_key=api_key)
    
    # IDEMPOTENCY: Load existing reports to avoid re-summarizing
    if Path(output_file).exists():
        try:
            reports = json.loads(Path(output_file).read_text())
            log.info(f"Loaded {len(reports)} existing community reports. Skipping duplicates.")
        except:
            reports = {}
    else:
        reports = {}

    for i, (cid, nodes) in enumerate(active_communities.items()):
        # Skip if already done
        if str(cid) in reports or cid in reports:
            continue
            
        log.info(f"[{i+1}/{len(active_communities)}] Summarizing Community {cid} ({len(nodes)} nodes)...")
        rels = community_rels.get(cid, [])
        try:
            report = summarizer.summarize_community(cid, nodes, rels)
        except Exception as e:
            log.error(f"Final failure for community {cid}: {e}")
            continue
        reports[cid] = {
            "community_id": cid,
            "title": report.split('\n')[0].replace('#', '').strip(),
            "report_markdown": report,
            "node_count": len(nodes)
        }
        
        # INCREMENTAL SAVE: Save after every report so we don't lose work
        Path(output_file).write_text(json.dumps(reports, indent=2))
        
        # Rate limiting / polite pause
        time.sleep(2)

    log.info(f"Saving {len(reports)} community reports to {output_file}...")
    Path(output_file).write_text(json.dumps(reports, indent=2))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", type=str, default="data/clustered_graph_v2.json")
    parser.add_argument("--output-file", type=str, default="data/community_reports_v2.json")
    args = parser.parse_args()

    API_KEY = os.environ.get("GOOGLE_API_KEY")
    if not API_KEY:
        log.error("GOOGLE_API_KEY not found.")
    else:
        run_community_summarization(
            args.input_file,
            args.output_file,
            API_KEY
        )
