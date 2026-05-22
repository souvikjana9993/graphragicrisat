/* ═══════════════════════════════════════════════════════════════
   ICRISAT GraphRAG — WebGL Force-Directed Graph Engine
   ═══════════════════════════════════════════════════════════════ */

const API_BASE = window.location.origin;

// ── Node color mapping ──
const NODE_COLORS = {
    Paper: '#06b6d4',
    Author: '#8b5cf6',
    Keyword: '#10b981',
    Crop: '#f59e0b',
    CROP: '#f59e0b',
    Topic: '#ec4899',
    Journal: '#6366f1',
    Funder: '#14b8a6',
    GeoLocation: '#f97316',
    Method: '#a855f7',
    METHOD: '#a855f7',
    Trait: '#22d3ee',
    TRAIT: '#22d3ee',
    GeneMarker: '#e879f9',
    GENE_MARKER: '#e879f9',
    Condition: '#fb923c',
    CONDITION: '#fb923c',
    ORGANISM: '#10b981',
    CONCEPT: '#3b82f6',
    LOCATION: '#ef4444'
};

// ── Edge color mapping ──
const EDGE_COLORS = {
    AUTHORED_BY: '#8b5cf6',
    HAS_KEYWORD: '#10b981',
    STUDIES_CROP: '#f59e0b',
    COVERS_TOPIC: '#ec4899',
    PUBLISHED_IN: '#6366f1',
    FUNDED_BY: '#14b8a6',
    LOCATED_IN: '#f97316',
    CO_AUTHORED: '#a78bfa',
    RELATED_TO: '#06b6d4',
    RELATES_TO: '#ef4444',
    USES_METHOD: '#a855f7',
    STUDIES_TRAIT: '#22d3ee',
    MENTIONS_GENE: '#e879f9',
    UNDER_CONDITION: '#fb923c',
    SIMILAR_TO: '#94a3b8',
};

// ── Node size by type ──
const NODE_BASE_SIZE = {
    Paper: 8,
    Author: 5,
    Keyword: 4,
    Crop: 7,
    Topic: 4,
    Journal: 5,
    Funder: 5,
    GeoLocation: 4,
    Method: 4,
    Trait: 4,
    GeneMarker: 3,
    Condition: 4,
};

// ── State ──
let graphData = { nodes: [], links: [] };
let Graph = null;
let selectedNode = null;
let showLabels = false;
let activeNodeTypes = new Set(Object.keys(NODE_COLORS));
let activeEdgeTypes = new Set(Object.keys(EDGE_COLORS));
let searchTimeout = null;

// ═══════════════════════════════════════════════════════════════
// Initialization
// ═══════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', init);

async function init() {
    setupEventListeners();
    await loadGraph();
}

// ═══════════════════════════════════════════════════════════════
// Data Loading
// ═══════════════════════════════════════════════════════════════

async function loadGraph() {
    try {
        const resp = await fetch(`${API_BASE}/api/graph`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        graphData = await resp.json();

        // Calculate node degrees for sizing
        const degreeMap = {};
        graphData.links.forEach(l => {
            const src = typeof l.source === 'object' ? l.source.id : l.source;
            const tgt = typeof l.target === 'object' ? l.target.id : l.target;
            degreeMap[src] = (degreeMap[src] || 0) + 1;
            degreeMap[tgt] = (degreeMap[tgt] || 0) + 1;
        });
        graphData.nodes.forEach(n => {
            n.degree = degreeMap[n.id] || 0;
            // WebGL optimization: precalculate val
            n.val = getNodeRadius(n);
        });

        // Initialize active sets from data
        const uniqueNodeTypes = new Set(graphData.nodes.map(n => n.type));
        const uniqueEdgeTypes = new Set(graphData.links.map(l => l.type));
        activeNodeTypes = new Set([...uniqueNodeTypes, ...Object.keys(NODE_COLORS)]);
        activeEdgeTypes = new Set([...uniqueEdgeTypes, ...Object.keys(EDGE_COLORS)]);

        // Update stats
        document.getElementById('stat-nodes').textContent = `${graphData.nodes.length} nodes`;
        document.getElementById('stat-edges').textContent = `${graphData.links.length} edges`;

        buildFilters();
        renderGraph();

        // Hide loading
        document.getElementById('loading-overlay').classList.add('hidden');
    } catch (err) {
        console.error('Failed to load graph:', err);
        document.querySelector('#loading-overlay p').textContent =
            `Failed to load graph: ${err.message}. Is the server running?`;
    }
}

// ═══════════════════════════════════════════════════════════════
// Filter Panels
// ═══════════════════════════════════════════════════════════════

function buildFilters() {
    // Count nodes per type
    const typeCounts = {};
    graphData.nodes.forEach(n => {
        typeCounts[n.type] = (typeCounts[n.type] || 0) + 1;
    });

    // Count edges per type
    const edgeCounts = {};
    graphData.links.forEach(l => {
        edgeCounts[l.type] = (edgeCounts[l.type] || 0) + 1;
    });

    // Build node type filters
    const typeFiltersEl = document.getElementById('type-filters');
    typeFiltersEl.innerHTML = '';
    Object.entries(typeCounts)
        .sort((a, b) => b[1] - a[1])
        .forEach(([type, count]) => {
            const el = document.createElement('div');
            el.className = 'type-filter';
            el.dataset.type = type;
            const safeType = type.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            el.innerHTML = `
                <div class="type-dot" style="background: ${NODE_COLORS[type] || '#666'}"></div>
                <span class="type-filter-label">${safeType}</span>
                <span class="type-filter-count">${count}</span>
            `;
            el.addEventListener('click', () => toggleNodeType(type, el));
            typeFiltersEl.appendChild(el);
        });

    // Build edge type filters
    const edgeFiltersEl = document.getElementById('edge-filters');
    edgeFiltersEl.innerHTML = '';
    Object.entries(edgeCounts)
        .sort((a, b) => b[1] - a[1])
        .forEach(([type, count]) => {
            const el = document.createElement('div');
            el.className = 'edge-filter';
            el.dataset.type = type;
            el.innerHTML = `
                <div class="edge-line" style="background: ${EDGE_COLORS[type] || '#666'}"></div>
                <span class="edge-filter-label">${type.replace(/_/g, ' ')}</span>
                <span class="edge-filter-count">${count}</span>
            `;
            el.addEventListener('click', () => toggleEdgeType(type, el));
            edgeFiltersEl.appendChild(el);
        });
}

function toggleNodeType(type, el) {
    if (activeNodeTypes.has(type)) {
        activeNodeTypes.delete(type);
        el.classList.add('disabled');
    } else {
        activeNodeTypes.add(type);
        el.classList.remove('disabled');
    }
    updateVisibility();
}

function toggleEdgeType(type, el) {
    if (activeEdgeTypes.has(type)) {
        activeEdgeTypes.delete(type);
        el.classList.add('disabled');
    } else {
        activeEdgeTypes.add(type);
        el.classList.remove('disabled');
    }
    updateVisibility();
}

function updateVisibility() {
    if (!Graph) return;
    
    // update data reference to trigger refresh of visibility
    Graph.nodeVisibility(node => activeNodeTypes.has(node.type));
    Graph.linkVisibility(link => {
        const srcType = link.source.type || (graphData.nodes.find(n => n.id === link.source) || {}).type;
        const tgtType = link.target.type || (graphData.nodes.find(n => n.id === link.target) || {}).type;
        return activeEdgeTypes.has(link.type) && activeNodeTypes.has(srcType) && activeNodeTypes.has(tgtType);
    });
}

// ═══════════════════════════════════════════════════════════════
// Graph Rendering (WebGL / ForceGraph)
// ═══════════════════════════════════════════════════════════════

function renderGraph() {
    const container = document.getElementById('graph-canvas');
    
    Graph = ForceGraph()(container)
        .graphData(graphData)
        .nodeId('id')
        .nodeVal(d => Math.sqrt(d.degree || 1) * 2 + 1)
        .nodeLabel(d => {
            let meta = d.type === 'Paper' ? `<br><i>${d.publication || d.date || ''}</i>` : '';
            return `<div style="background: #0f172aee; padding: 6px 10px; border-radius: 4px; font-family: Inter; font-size: 12px; border: 1px solid #334155;">
                <span style="color: ${NODE_COLORS[d.type] || '#aaa'}; font-weight: bold; font-size: 10px; text-transform: uppercase;">${d.type}</span><br>
                <b>${d.display_name || d.id}</b>${meta}
            </div>`;
        })
        .nodeColor(d => {
            if (selectedNode) {
                // Highlighting logic
                const isSelected = d.id === selectedNode.id;
                const isNeighbor = graphData.links.some(l => 
                    (l.source.id === selectedNode.id && l.target.id === d.id) ||
                    (l.target.id === selectedNode.id && l.source.id === d.id)
                );
                if (isSelected) return NODE_COLORS[d.type] || '#666';
                if (isNeighbor) return NODE_COLORS[d.type] || '#666';
                return '#334155'; // dimmed
            }
            return NODE_COLORS[d.type] || '#666';
        })
        .linkColor(d => {
            if (selectedNode) {
                const isConnected = d.source.id === selectedNode.id || d.target.id === selectedNode.id;
                return isConnected ? (EDGE_COLORS[d.type] || '#94a3b8') : '#1e293b'; // dimmed
            }
            return EDGE_COLORS[d.type] || '#334155';
        })
        .linkWidth(d => {
            if (selectedNode) {
                const isConnected = d.source.id === selectedNode.id || d.target.id === selectedNode.id;
                return isConnected ? 2 : 0.5;
            }
            return 1;
        })
        .onNodeClick(node => {
            selectNode(node);
            Graph.centerAt(node.x, node.y, 1000);
            Graph.zoom(3, 1000);
        })
        .onBackgroundClick(() => {
            deselectNode();
        });
        
    // Customize force layout parameters
    Graph.d3Force('charge').strength(-150);
    Graph.d3Force('link').distance(60);
    
    // Add text labels if enabled
    Graph.nodeCanvasObjectMode(() => showLabels ? 'after' : undefined);
    Graph.nodeCanvasObject((node, ctx, globalScale) => {
        if (!showLabels) return;
        const label = truncate(node.display_name || node.id, 20);
        const fontSize = 12/globalScale;
        ctx.font = `${fontSize}px Sans-Serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#cbd5e1';
        ctx.fillText(label, node.x, node.y + Math.sqrt(Math.max(0, node.val)) + fontSize);
    });
}

function getNodeRadius(d) {
    const base = NODE_BASE_SIZE[d.type] || 4;
    // Scale by degree (log scale to avoid massive nodes)
    return base + Math.log2(1 + (d.degree || 0)) * 1.5;
}

function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? str.slice(0, len) + '…' : str;
}


// ═══════════════════════════════════════════════════════════════
// Node Selection & Detail Panel
// ═══════════════════════════════════════════════════════════════

async function selectNode(d) {
    selectedNode = d;

    // Trigger re-render of colors and widths for highlighting
    if (Graph) {
        Graph.nodeColor(Graph.nodeColor());
        Graph.linkColor(Graph.linkColor());
        Graph.linkWidth(Graph.linkWidth());
    }

    // Build detail panel
    const panel = document.getElementById('right-panel');
    const title = document.getElementById('detail-title');
    const content = document.getElementById('detail-content');

    title.textContent = d.display_name || d.id;
    title.style.color = NODE_COLORS[d.type] || '#fff';

    let html = `<div class="detail-section">
        <div class="detail-label">Type</div>
        <div class="detail-value">
            <span class="detail-tag" style="background: ${NODE_COLORS[d.type] || '#666'}22; color: ${NODE_COLORS[d.type] || '#666'}; border: 1px solid ${NODE_COLORS[d.type] || '#666'}44">
                ${d.type.replace(/</g, '&lt;').replace(/>/g, '&gt;')}
            </span>
        </div>
    </div>`;

    if (d.community !== undefined && d.community !== -1) {
        html += `<div class="detail-section">
            <div class="detail-label">Community</div>
            <div class="detail-value">
                <span style="font-weight: 500;">Level 0:</span> ${d.community} | 
                <span style="font-weight: 500;">Level 1:</span> ${d.community_L1}
            </div>
        </div>`;
    }

    if (d.description) {
        html += `<div class="detail-section">
            <div class="detail-label">Description</div>
            <div class="detail-value" style="font-style: italic; color: #cbd5e1;">${d.description}</div>
        </div>`;
    }

    // Type-specific details
    if (d.type === 'Paper') {
        if (d.abstract) {
            html += `<div class="detail-section">
                <div class="detail-label">Abstract</div>
                <div class="detail-value">${d.abstract}</div>
            </div>`;
        }
        if (d.date) {
            html += `<div class="detail-section">
                <div class="detail-label">Date</div>
                <div class="detail-value">${d.date}</div>
            </div>`;
        }
        if (d.publication) {
            html += `<div class="detail-section">
                <div class="detail-label">Journal</div>
                <div class="detail-value">${d.publication}</div>
            </div>`;
        }
        if (d.uri) {
            html += `<div class="detail-section">
                <div class="detail-label">Link</div>
                <a href="${d.uri}" target="_blank" class="detail-link">${d.uri}</a>
            </div>`;
        }
    }

    // Neighbors list
    const neighbors = [];
    graphData.links.forEach(l => {
        const src = typeof l.source === 'object' ? l.source : graphData.nodes.find(n => n.id === l.source);
        const tgt = typeof l.target === 'object' ? l.target : graphData.nodes.find(n => n.id === l.target);
        if (src?.id === d.id && tgt) {
            neighbors.push({ node: tgt, edgeType: l.type });
        } else if (tgt?.id === d.id && src) {
            neighbors.push({ node: src, edgeType: l.type });
        }
    });

    if (neighbors.length > 0) {
        // Group by edge type
        const grouped = {};
        neighbors.forEach(n => {
            if (!grouped[n.edgeType]) grouped[n.edgeType] = [];
            grouped[n.edgeType].push(n.node);
        });

        html += `<div class="detail-section"><div class="detail-label">Connections (${neighbors.length})</div>`;
        for (const [edgeType, nodes] of Object.entries(grouped)) {
            html += `<div style="margin-bottom: 8px; font-size: 11px; color: ${EDGE_COLORS[edgeType] || '#666'}; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 10px">${edgeType.replace(/_/g, ' ')}</div>`;
            html += `<ul class="neighbor-list">`;
            nodes.slice(0, 15).forEach(n => {
                html += `<li class="neighbor-item" data-node-id="${n.id}">
                    <span class="neighbor-dot" style="background: ${NODE_COLORS[n.type] || '#666'}"></span>
                    ${truncate(n.display_name || n.id, 30)}
                </li>`;
            });
            if (nodes.length > 15) {
                html += `<li class="neighbor-item" style="color: var(--text-muted); font-style: italic">...and ${nodes.length - 15} more</li>`;
            }
            html += `</ul>`;
        }
        html += `</div>`;
    }

    content.innerHTML = html;

    // Add click handlers to neighbor items
    content.querySelectorAll('.neighbor-item[data-node-id]').forEach(el => {
        el.addEventListener('click', () => {
            const nodeId = el.dataset.nodeId;
            const node = graphData.nodes.find(n => n.id === nodeId);
            if (node) {
                selectNode(node);
                Graph.centerAt(node.x, node.y, 1000);
            }
        });
    });

    panel.classList.remove('hidden');
}

function deselectNode() {
    selectedNode = null;
    if (Graph) {
        Graph.nodeColor(Graph.nodeColor());
        Graph.linkColor(Graph.linkColor());
        Graph.linkWidth(Graph.linkWidth());
    }
    document.getElementById('right-panel').classList.add('hidden');
}

// ═══════════════════════════════════════════════════════════════
// Search
// ═══════════════════════════════════════════════════════════════

function handleSearch(query) {
    const resultsEl = document.getElementById('search-results');

    if (!query || query.length < 2) {
        resultsEl.classList.add('hidden');
        return;
    }

    const q = query.toLowerCase();
    const matches = graphData.nodes
        .filter(n => (n.display_name || n.id).toLowerCase().includes(q))
        .slice(0, 15);

    if (matches.length === 0) {
        resultsEl.innerHTML = '<div class="search-result-item"><span class="result-name" style="color: var(--text-muted)">No results found</span></div>';
    } else {
        resultsEl.innerHTML = matches.map(n => `
            <div class="search-result-item" data-node-id="${n.id}">
                <span class="result-type-badge" style="background: ${NODE_COLORS[n.type] || '#666'}22; color: ${NODE_COLORS[n.type] || '#666'}">${n.type.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</span>
                <span class="result-name">${n.display_name || n.id}</span>
            </div>
        `).join('');
    }

    resultsEl.classList.remove('hidden');

    // Click handlers
    resultsEl.querySelectorAll('.search-result-item[data-node-id]').forEach(el => {
        el.addEventListener('click', () => {
            const node = graphData.nodes.find(n => n.id === el.dataset.nodeId);
            if (node) {
                selectNode(node);
                // Center on node
                if (Graph) {
                    Graph.centerAt(node.x, node.y, 1000);
                    Graph.zoom(4, 1000);
                }
            }
            resultsEl.classList.add('hidden');
            document.getElementById('search-input').value = '';
        });
    });
}

// ═══════════════════════════════════════════════════════════════
// LLM Query
// ═══════════════════════════════════════════════════════════════

async function submitQuery() {
    const input = document.getElementById('query-input');
    const resultsEl = document.getElementById('query-results');
    const query = input.value.trim();
    
    // Get active mode and hops
    const mode = document.querySelector('input[name="query-mode"]:checked').value;
    const hops = parseInt(document.getElementById('query-hops').value);

    if (!query) return;

    resultsEl.innerHTML = `<div class="query-loading"><div class="spinner" style="width:24px;height:24px;border-width:2px;margin:0"></div>Searching the knowledge graph [${mode}, hops: ${hops}]...</div>`;

    try {
        const resp = await fetch(`${API_BASE}/api/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, mode, hops, max_results: 10 }),
        });

        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP ${resp.status}`);
        }
        const data = await resp.json();

        let html = '';
        if (data.explanation) {
            html += `<div class="query-explanation">${data.explanation}</div>`;
        }

        if (data.papers && data.papers.length > 0) {
            data.papers
                .sort((a, b) => (b.score || 0) - (a.score || 0))
                .forEach(p => {
                    html += `<div class="query-result-card" data-eprint-id="${p.eprint_id}">
                        <div class="query-result-title">${p.title}</div>
                        <div class="query-result-reason">${p.relevance_reason}</div>
                        <div class="query-result-score">Relevance: ${(p.score * 100).toFixed(0)}%</div>
                    </div>`;
                });
        } else {
            html += '<div style="color: var(--text-muted); padding: 20px; text-align: center">No relevant papers found.</div>';
        }

        resultsEl.innerHTML = html;

        // Click to navigate to paper
        resultsEl.querySelectorAll('.query-result-card').forEach(el => {
            el.addEventListener('click', () => {
                const eid = el.dataset.eprintId;
                const node = graphData.nodes.find(n => n.eprint_id == eid || n.id === `paper_${eid}`);
                if (node) {
                    selectNode(node);
                    document.getElementById('query-modal').classList.add('hidden');
                    if (Graph) {
                        Graph.centerAt(node.x, node.y, 1000);
                        Graph.zoom(4, 1000);
                    }
                }
            });
        });

    } catch (err) {
        resultsEl.innerHTML = `<div style="color: var(--accent-danger); padding: 20px">Query failed: ${err.message}</div>`;
    }
}

// ═══════════════════════════════════════════════════════════════
// Event Listeners
// ═══════════════════════════════════════════════════════════════

function setupEventListeners() {
    // Search
    const searchInput = document.getElementById('search-input');
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => handleSearch(e.target.value), 200);
    });
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.getElementById('search-results').classList.add('hidden');
            searchInput.blur();
        }
    });

    // Close search results when clicking outside
    document.addEventListener('click', (e) => {
        if (!document.getElementById('search-container').contains(e.target)) {
            document.getElementById('search-results').classList.add('hidden');
        }
    });

    // Close detail panel
    document.getElementById('btn-close-detail').addEventListener('click', deselectNode);

    // Reset view
    document.getElementById('btn-reset-view').addEventListener('click', () => {
        deselectNode();
        if (Graph) {
            Graph.zoomToFit(1000, 50);
        }
    });

    // Toggle labels
    document.getElementById('btn-toggle-labels').addEventListener('click', () => {
        showLabels = !showLabels;
        if (Graph) Graph.nodeCanvasObjectMode(() => showLabels ? 'after' : undefined);
    });

    // Hop slider
    document.getElementById('hop-slider').addEventListener('input', (e) => {
        document.getElementById('hop-value').textContent = e.target.value;
    });

    // Link strength
    document.getElementById('link-strength').addEventListener('input', (e) => {
        if (Graph) {
            Graph.d3Force('link').distance(Number(e.target.value) * 2);
            Graph.d3ReheatSimulation();
        }
    });

    // Charge strength
    document.getElementById('charge-strength').addEventListener('input', (e) => {
        if (Graph) {
            Graph.d3Force('charge').strength(-Number(e.target.value));
            Graph.d3ReheatSimulation();
        }
    });

    // Hops slider
    const hopsSlider = document.getElementById('query-hops');
    if (hopsSlider) {
        hopsSlider.addEventListener('input', (e) => {
            document.getElementById('hops-value').textContent = e.target.value;
        });
    }

    // Mode selector
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.mode-btn').forEach(b => {
                b.classList.remove('active');
                b.style.background = '#1e293b';
                b.style.borderColor = '#334155';
                b.style.color = '#94a3b8';
            });
            btn.classList.add('active');
            btn.style.background = '#334155';
            btn.style.borderColor = '#6366f1';
            btn.style.color = '#fff';
            btn.querySelector('input').checked = true;
            
            // Toggle hops slider visibility
            const val = btn.querySelector('input').value;
            const hopsContainer = document.getElementById('hops-container');
            if (val === 'global' || val === 'naive') {
                hopsContainer.style.display = 'none';
            } else {
                hopsContainer.style.display = 'block';
            }
        });
    });

    // Query modal
    document.getElementById('fab-query').addEventListener('click', () => {
        document.getElementById('query-modal').classList.remove('hidden');
        document.getElementById('query-input').focus();
    });
    document.getElementById('btn-close-modal').addEventListener('click', () => {
        document.getElementById('query-modal').classList.add('hidden');
    });
    document.getElementById('btn-query').addEventListener('click', submitQuery);
    document.getElementById('query-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') submitQuery();
    });

    // Window resize
    window.addEventListener('resize', () => {
        if (Graph) {
            const container = document.getElementById('graph-container');
            Graph.width(container.clientWidth).height(container.clientHeight);
        }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === '/' && !e.ctrlKey && document.activeElement.tagName !== 'INPUT') {
            e.preventDefault();
            searchInput.focus();
        }
        if (e.key === 'Escape') {
            document.getElementById('query-modal').classList.add('hidden');
            deselectNode();
        }
    });
}
