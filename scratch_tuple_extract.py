import json
import re
from pathlib import Path
from google import genai

client = genai.Client(api_key='AIzaSyBobxOnj0_hifJrndYrN480PQGYJFqGB1M')

# Load paper 2 (groundnut drought QTL paper)
paper = json.loads(Path('data/raw_metadata/2.json').read_text())
title = paper['title']
abstract = paper['abstract']
paper_id = "paper_2"

print(f"=== Paper: {title[:80]}... ===")
print(f"Abstract length: {len(abstract)} chars\n")

EXTRACTION_PROMPT = """
-Goal-
Given a research abstract from ICRISAT, identify all entities of specific types and all relationships among them.

-Steps-
1. Identify all entities. Extract:
- entity_name: Name of the entity, CAPITALIZED (e.g. GROUNDNUT, QTL MAPPING, DROUGHT TOLERANCE). Always use the most common English scientific/agricultural name.
- entity_type: One of: CROP, TRAIT, METHOD, GENE_MARKER, CONDITION, ORGANISM, CONCEPT, LOCATION
- entity_description: Comprehensive description of the entity's attributes in this context.
Format each entity EXACTLY as: ("entity"|<entity_name>|<entity_type>|<entity_description>)

2. Identify relationships between the entities you found.
Format each relationship EXACTLY as: ("relationship"|<source_entity_name>|<target_entity_name>|<relationship_description>|<relationship_strength>)
where <relationship_strength> is a numeric score from 1 to 10 indicating how strongly they are related.

Return output as a single list of these tuples. Use ## as the delimiter between tuples. Do not include any markdown blocks, json, or conversational text.

Title: {title}
Abstract: {abstract}
"""

prompt = EXTRACTION_PROMPT.format(title=title, abstract=abstract)

print("Running LLM Extraction...\n")
response = client.models.generate_content(
    model='gemma-3-27b-it',
    contents=prompt,
    config={'temperature': 0.1},
)

raw_text = response.text.strip()
print("=== RAW LLM OUTPUT ===")
print(raw_text)
print("======================\n")

# Parse the tuples
entities = []
relationships = []

records = [r.strip() for r in raw_text.split("##")]
for raw_record in records:
    # Clean up outer parens if present
    record = re.sub(r"^\(|\)$", "", raw_record.strip())
    if not record:
        continue
    
    attributes = record.split("|")
    record_type = attributes[0].strip().replace('"', '')
    
    if record_type == "entity" and len(attributes) >= 4:
        entities.append({
            "name": attributes[1].strip().upper(),
            "type": attributes[2].strip().upper(),
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

print(f"=== PARSED RESULTS ===")
print(f"Parsed {len(entities)} Entities:")
for e in entities:
    print(f"  [{e['type']}] {e['name']}: {e['description'][:60]}...")

print(f"\nParsed {len(relationships)} Relationships:")
for r in relationships:
    print(f"  {r['source']} -> {r['target']} ({r['weight']}): {r['description'][:60]}...")
