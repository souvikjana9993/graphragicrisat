#!/usr/bin/env bash
# Run the full ICRISAT GraphRAG pipeline
# Usage: bash run.sh [scrape|extract|build|serve|all]

set -e
cd "$(dirname "$0")"

# Activate venv
source venv/bin/activate

export GOOGLE_API_KEY="${GOOGLE_API_KEY:-AIzaSyBobxOnj0_hifJrndYrN480PQGYJFqGB1M}"

case "${1:-help}" in
    scrape)
        echo "═══ Scraping metadata from ICRISAT OAR ═══"
        python -m scraper.fetch_metadata --start "${2:-2}" --end "${3:-200}" --resume
        ;;
    extract)
        echo "═══ Extracting entities with Gemma 4 ═══"
        python -m graph.entity_extractor --api-key "$GOOGLE_API_KEY"
        ;;
    build)
        echo "═══ Building knowledge graph ═══"
        python -m graph.build_graph ${2:+--skip-llm}
        ;;
    serve)
        echo "═══ Starting server on http://localhost:8000 ═══"
        uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
        ;;
    all)
        echo "═══ Running full pipeline ═══"
        echo "Step 1: Scraping..."
        python -m scraper.fetch_metadata --start "${2:-2}" --end "${3:-200}" --resume
        echo "Step 2: Entity extraction..."
        python -m graph.entity_extractor --api-key "$GOOGLE_API_KEY"
        echo "Step 3: Building graph..."
        python -m graph.build_graph
        echo "Step 4: Starting server..."
        uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
        ;;
    status)
        echo "═══ Pipeline Status ═══"
        echo "Scraped papers: $(ls data/raw_metadata/*.json 2>/dev/null | grep -v _raw | wc -l)"
        echo "LLM extractions: $(ls data/llm_extractions/*.json 2>/dev/null | wc -l)"
        if [ -f data/graph_stats.json ]; then
            echo "Graph stats:"
            cat data/graph_stats.json | python3 -m json.tool
        fi
        ;;
    *)
        echo "ICRISAT GraphRAG Pipeline"
        echo ""
        echo "Usage: bash run.sh <command>"
        echo ""
        echo "Commands:"
        echo "  scrape [start] [end]  Scrape metadata (default: 2-200)"
        echo "  extract               Run LLM entity extraction"
        echo "  build [--skip-llm]    Build knowledge graph"
        echo "  serve                 Start web server"
        echo "  all [start] [end]     Run full pipeline"
        echo "  status                Show pipeline status"
        ;;
esac
