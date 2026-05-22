import sqlite3
import json
from pathlib import Path

DB_PATH = Path("data/subset_1k/pilot_graph.db")

def print_header(title):
    print(f"\n{'='*80}\n{title}\n{'='*80}")

def query_top_communities(cursor, limit=3):
    print_header(f"Top {limit} Largest AI-Generated Community Reports")
    cursor.execute('''
        SELECT id, title, node_count, report 
        FROM communities 
        ORDER BY node_count DESC LIMIT ?
    ''', (limit,))
    
    for row in cursor.fetchall():
        cid, title, count, report = row
        print(f"Community {cid}: {title} ({count} nodes)")
        # Print a snippet of the report
        report_snippet = "\n".join(report.split("\n")[:4])
        print(f"Snippet:\n{report_snippet}\n...\n")

def query_top_entities(cursor, limit=5):
    print_header(f"Top {limit} Most Mentioned Entities")
    # type != 'Paper' means it's an entity/topic/crop/author etc
    # Let's filter for LLM extracted concepts, which typically have types like CROP, TRAIT, METHOD
    cursor.execute('''
        SELECT display_name, type, json_extract(data, '$.frequency') as freq 
        FROM nodes 
        WHERE type IN ('CROP', 'TRAIT', 'METHOD', 'LOCATION', 'CONCEPT') 
        ORDER BY freq DESC LIMIT ?
    ''', (limit,))
    
    for i, row in enumerate(cursor.fetchall()):
        name, type_, freq = row
        print(f"{i+1}. {name} ({type_}) - Mentions: {freq}")

def query_entity_relationships(cursor, entity_name="GROUNDNUT", limit=5):
    print_header(f"Top Relationships for Entity: {entity_name}")
    # We find relationships where the source or target matches the entity
    # Nodes are prefixed with 'llm_' so we match by display_name
    cursor.execute('''
        SELECT n1.display_name, n2.display_name, e.type, json_extract(e.data, '$.description') 
        FROM edges e
        JOIN nodes n1 ON e.source = n1.id
        JOIN nodes n2 ON e.target = n2.id
        WHERE (n1.display_name = ? OR n2.display_name = ?) 
          AND e.type = 'RELATES_TO'
        LIMIT ?
    ''', (entity_name, entity_name, limit))
    
    for row in cursor.fetchall():
        source, target, edge_type, desc = row
        print(f"- {source} <--> {target}")
        if desc:
            print(f"  Context: {desc}")

def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    query_top_communities(c)
    query_top_entities(c)
    query_entity_relationships(c, "GROUNDNUT")

    conn.close()

if __name__ == "__main__":
    main()
