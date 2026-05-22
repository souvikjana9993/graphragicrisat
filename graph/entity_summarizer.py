"""
Entity and Relationship Summarizer (Microsoft GraphRAG style).
Takes merged entities with multiple descriptions and uses Gemma to generate a single concise canonical description.
"""

import json
import logging
import os
import time
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from google import genai
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SUMMARIZE_PROMPT = """
You are an expert scientific summarizer. Given a list of descriptions for the exact same entity or relationship found across multiple research papers, synthesize them into a single, comprehensive, and concise canonical description.

Do not use conversational language. Just output the summary paragraph.

Name: {name}
Type: {type}

Descriptions to summarize:
{descriptions}
"""

class GraphSummarizer:
    def __init__(self, api_key: str, model_name: str = "models/gemma-4-31b-it"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.request_count = 0
        self.delay_seconds = 2.0  # Reduced delay for burst mode during pilot finishing

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def summarize_list(self, name: str, item_type: str, descriptions: list[str]) -> str:
        """Summarize a list of descriptions with robust retries."""
        if len(descriptions) > 30:
            descriptions = descriptions[:30]
            
        desc_text = "\n".join([f"- {d}" for d in descriptions])
        prompt = SUMMARIZE_PROMPT.format(name=name, type=item_type, descriptions=desc_text)

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config={"temperature": 0.1},
        )
        return response.text.strip()

def run_summarization(input_file: str, output_file: str, api_key: str, top_n: int = 500):
    if Path(output_file).exists():
        log.info(f"Loading existing summaries from {output_file} to resume...")
        data = json.loads(Path(output_file).read_text())
    else:
        log.info(f"Loading merged graph from {input_file}...")
        data = json.loads(Path(input_file).read_text())
    
    entities = data.get("entities", [])
    relationships = data.get("relationships", [])
    
    # SORT BY FREQUENCY: Prioritize the most important entities
    entities.sort(key=lambda x: x.get("frequency", 1), reverse=True)
    relationships.sort(key=lambda x: x.get("frequency", 1), reverse=True)
    
    summarizer = GraphSummarizer(api_key=api_key)
    
    log.info(f"Summarizing Top {top_n} Entities...")
    for i, entity in enumerate(entities):
        descs = entity.get("descriptions", [])
        
        # Only summarize the TOP N or if they have multi-descriptions
        if i < top_n and len(descs) > 1:
            if entity.get("canonical_description"):
                log.info(f"[{i+1}/{top_n}] Skipping '{entity['name']}' (already summarized).")
                continue
            log.info(f"[{i+1}/{top_n}] Summarizing '{entity['name']}' ({len(descs)} sources)...")
            try:
                entity["canonical_description"] = summarizer.summarize_list(entity["name"], entity["type"], descs)
            except Exception as e:
                log.error(f"Final failure for '{entity['name']}': {e}")
                entity["canonical_description"] = descs[0]
        elif len(descs) >= 1:
            entity["canonical_description"] = descs[0]
        else:
            entity["canonical_description"] = ""
            
    log.info(f"Summarizing Top {top_n // 2} Relationships...")
    for i, rel in enumerate(relationships):
        rel_key = f"{rel['source']} -> {rel['target']}"
        descs = rel.get("descriptions", [])
        
        if i < (top_n // 2) and len(descs) > 1:
            log.info(f"[{i+1}/{top_n // 2}] Summarizing relation '{rel_key}' ({len(descs)} sources)...")
            try:
                rel["canonical_description"] = summarizer.summarize_list(rel_key, "RELATIONSHIP", descs)
            except Exception as e:
                log.error(f"Final failure for relation '{rel_key}': {e}")
                rel["canonical_description"] = descs[0]
        elif len(descs) >= 1:
            rel["canonical_description"] = descs[0]
        else:
            rel["canonical_description"] = ""
            
    export_data = {
        "entities": entities,
        "relationships": relationships
    }
    
    Path(output_file).write_text(json.dumps(export_data, indent=2))
    log.info(f"Saved summarized graph to {output_file}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", type=str, default="data/merged_graph_v2.json")
    parser.add_argument("--output-file", type=str, default="data/summarized_graph_v2.json")
    parser.add_argument("--top-n", type=int, default=500)
    args = parser.parse_args()
    
    API_KEY = os.environ.get("GOOGLE_API_KEY")
    run_summarization(args.input_file, args.output_file, API_KEY, args.top_n)
