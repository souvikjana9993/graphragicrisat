import argparse
import json
import sqlite3
import logging
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

class GraphQueryEngine:
    def __init__(self, db_path: str, api_key: str = None, model_name: str = "gemma-4-31b-it"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        
        # Load API key from env if not provided
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        before_sleep=lambda retry_state: log.warning(f"LLM extraction failed (attempt {retry_state.attempt_number}/7), retrying in {retry_state.next_action.sleep}s...")
    )
    def extract_entities_from_query(self, query: str) -> list[str]:
        """Use LLM to extract key entities from the user's natural language query."""
        log.info("Extracting entities from query using LLM...")
        
        prompt = f"""
Given the following user query, extract the core agricultural, scientific, or geographical entities.
Return ONLY a comma-separated list of the entities in UPPERCASE. Do not include any conversational text.

Query: {query}
"""
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={"temperature": 0.0}
            )
            raw_text = response.text.strip()
            # Parse comma separated list
            entities = [e.strip().upper() for e in raw_text.split(",") if e.strip()]
            log.info(f"Extracted Entities: {entities}")
            return entities
        except Exception as e:
            raise e

    def get_node_ids_by_name(self, name: str) -> list[str]:
        """Find all node IDs that match an exact display name."""
        c = self.conn.cursor()
        c.execute("SELECT id FROM nodes WHERE upper(display_name) = ?", (name.upper(),))
        return [row["id"] for row in c.fetchall()]

    def get_community_report(self, community_id: int) -> dict | None:
        """Fetch the AI-generated report for a given community."""
        c = self.conn.cursor()
        c.execute("SELECT title, report FROM communities WHERE id = ?", (community_id,))
        row = c.fetchone()
        if row:
            return {"title": row["title"], "report": row["report"]}
        return None

    def get_papers_in_community(self, community_id: int, limit: int = 10) -> list[dict]:
        """Fetch papers connected to entities that belong to a specific community."""
        c = self.conn.cursor()
        query = """
            SELECT DISTINCT n.id, n.display_name 
            FROM nodes n
            JOIN edges e ON (n.id = e.source OR n.id = e.target)
            JOIN nodes n_community ON (n_community.id = e.target OR n_community.id = e.source)
            WHERE n.type = 'PAPER' 
              AND json_extract(n_community.data, '$.community') = ?
            LIMIT ?
        """
        c.execute(query, (community_id, limit))
        return [{"id": row["id"], "title": row["display_name"]} for row in c.fetchall()]

    def local_search(self, start_nodes: list[str], hops: int = 1) -> dict:
        """Perform an N-hop traversal from the starting nodes."""
        log.info(f"Performing {hops}-hop local search from {len(start_nodes)} nodes...")
        
        visited_nodes = set(start_nodes)
        current_frontier = set(start_nodes)
        
        all_edges = []
        paper_hit_count = Counter()
        c = self.conn.cursor()

        for hop in range(hops):
            if not current_frontier:
                break
                
            next_frontier = set()
            placeholders = ",".join("?" * len(current_frontier))
            
            # Find all edges where source OR target is in the current frontier
            c.execute(f"""
                SELECT source, target, type, data 
                FROM edges 
                WHERE source IN ({placeholders}) OR target IN ({placeholders})
            """, tuple(current_frontier) * 2)
            
            rows = c.fetchall()
            for row in rows:
                source = row["source"]
                target = row["target"]
                edge_type = row["type"]
                data = json.loads(row["data"])
                
                # Format a readable relationship string
                desc = data.get("description", "")
                rel_str = f"[{source}] -({edge_type})-> [{target}]"
                if desc:
                    rel_str += f": {desc}"
                
                all_edges.append(rel_str)
                
                # Track paper hits for relevance sorting
                if source.startswith("paper_"):
                    paper_hit_count[source] += 1
                if target.startswith("paper_"):
                    paper_hit_count[target] += 1
                
                # Add unvisited neighbors to next frontier
                if source not in visited_nodes:
                    visited_nodes.add(source)
                    next_frontier.add(source)
                if target not in visited_nodes:
                    visited_nodes.add(target)
                    next_frontier.add(target)
            
            current_frontier = next_frontier

        # Deduplicate edges
        all_edges = list(set(all_edges))
        
        # Also, find which communities these visited nodes belong to and count hits
        community_counts = Counter()
        if visited_nodes:
            placeholders = ",".join("?" * len(visited_nodes))
            c.execute(f"""
                SELECT json_extract(data, '$.community') as cid
                FROM nodes
                WHERE id IN ({placeholders})
            """, tuple(visited_nodes))
            
            for row in c.fetchall():
                cid = row["cid"]
                if cid is not None and cid != -1:
                    community_counts[cid] += 1
                    
        # Sort communities by relevance (number of node hits)
        sorted_communities = [cid for cid, count in community_counts.most_common()]
                    
        # Fetch metadata for all visited papers
        papers = []
        if visited_nodes:
            placeholders = ",".join("?" * len(visited_nodes))
            c.execute(f"""
                SELECT id, display_name
                FROM nodes
                WHERE type = 'PAPER' AND id IN ({placeholders})
            """, tuple(visited_nodes))
            papers = [{"id": row["id"], "title": row["display_name"]} for row in c.fetchall()]
            
            # Sort papers by their graph relevance (hit count)
            papers.sort(key=lambda p: paper_hit_count[p["id"]], reverse=True)
                    
        return {
            "relationships": all_edges,
            "communities": sorted_communities,
            "papers": papers
        }

    def query(self, user_query: str, hops: int = 1) -> str:
        """Run the full Hybrid GraphRAG pipeline."""
        
        # 1. Semantic Entity Extraction
        try:
            entities = self.extract_entities_from_query(user_query)
        except Exception as e:
            log.error(f"Failed to extract entities after retries: {e}")
            return "Failed to process query due to LLM errors. Please try again later."
            
        if not entities:
            return "No entities found in query. Please try rephrasing."

        # 2. Map entities to Graph Node IDs
        start_nodes = []
        for e in entities:
            node_ids = self.get_node_ids_by_name(e)
            if node_ids:
                start_nodes.extend(node_ids)
            else:
                log.warning(f"Entity '{e}' not found in the graph.")

        if not start_nodes:
            return "None of the extracted entities exist in the knowledge graph."

        # 3. Local Search (N-Hop)
        local_context = self.local_search(start_nodes, hops=hops)
        
        # 4. Global Community Context
        community_contexts = []
        # To avoid context overload, limit to top 3 communities hit
        top_communities = local_context["communities"][:3] 
        
        for cid in top_communities:
            try:
                cid = int(cid)
            except ValueError:
                continue
                
            report_data = self.get_community_report(cid)
            if report_data:
                # Fetch papers connected to this community
                community_papers = self.get_papers_in_community(cid, limit=15)
                paper_list_str = ""
                if community_papers:
                    paper_list_str = "\n**Source Papers for this Community:**\n"
                    paper_list_str += "\n".join([f"   - {p['title']} (ID: {p['id']})" for p in community_papers])
                    paper_list_str += "\n"

                ctx = f"### Community: {report_data['title']}\n"
                ctx += f"{report_data['report']}\n"
                ctx += paper_list_str
                community_contexts.append(ctx)

        # 5. Assemble Final Context Block
        output = "==================================================\n"
        output += "GRAPH RAG CONTEXT INJECTION BLOCK\n"
        output += "==================================================\n\n"
        
        output += "## 0. EXTRACTED ENTITIES FROM QUERY\n"
        output += f"[{', '.join(entities)}]\n\n"
        
        output += "## 1. RELEVANT PAPERS (" + str(hops) + "-Hop)\n"
        if local_context["papers"]:
            for p in local_context["papers"][:20]:
                output += f"- {p['title']} (ID: {p['id']})\n"
            if len(local_context["papers"]) > 20:
                output += f"... and {len(local_context['papers']) - 20} more papers.\n"
        else:
            output += "No specific papers found.\n"
        
        output += "\n## 2. LOCAL GRAPH RELATIONSHIPS\n"
        if local_context["relationships"]:
            for rel in local_context["relationships"][:50]: # Limit to 50
                output += f"- {rel}\n"
            if len(local_context["relationships"]) > 50:
                output += f"... and {len(local_context['relationships']) - 50} more relationships.\n"
        else:
            output += "No specific relationships found.\n"

        output += "\n## 2. GLOBAL COMMUNITY SUMMARIES & SOURCE PAPERS\n"
        if community_contexts:
            output += "\n\n".join(community_contexts)
        else:
            output += "No overarching communities found for these entities.\n"
            
        output += "\n==================================================\n"
        
        return output

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query the Knowledge Graph for Hybrid RAG injection.")
    parser.add_argument("query", type=str, help="The user's natural language query.")
    parser.add_argument("--db", type=str, default="data/graph_6k.db", help="Path to SQLite graph DB.")
    parser.add_argument("--hops", type=int, default=1, help="Number of hops for local search (default: 1).")
    
    args = parser.parse_args()
    
    engine = GraphQueryEngine(db_path=args.db)
    
    print(f"\nProcessing Query: '{args.query}'\n")
    context = engine.query(args.query, hops=args.hops)
    
    print(context)
    engine.close()
