"""
Node matching and entity resolution for the ICRISAT knowledge graph.

Handles deduplication and normalization of:
- Authors (canonical key from structured name fields)
- Keywords (3-layer normalization)
- Crops (alias table + scientific names)
- Journals (normalized name)
- Locations (from geopolitical tags)
- Funders (normalized name)
"""

import re
from collections import defaultdict


# ──────────────────────────────────────────────────────────────────────
# Crop alias table — maps variant names to canonical crop names
# ──────────────────────────────────────────────────────────────────────

CROP_ALIASES = {
    "groundnut": {
        "canonical": "Groundnut",
        "scientific": "Arachis hypogaea",
        "aliases": [
            "peanut", "arachis hypogaea", "arachis hypogaea l.",
            "arachis hypogaea l", "groundnuts",
        ],
    },
    "chickpea": {
        "canonical": "Chickpea",
        "scientific": "Cicer arietinum",
        "aliases": [
            "cicer arietinum", "cicer arietinum l.", "cicer arietinum l",
            "bengal gram", "chana", "chickpeas", "gram",
        ],
    },
    "pigeonpea": {
        "canonical": "Pigeonpea",
        "scientific": "Cajanus cajan",
        "aliases": [
            "pigeon pea", "cajanus cajan", "red gram", "arhar",
            "toor", "tur", "pigeonpeas",
        ],
    },
    "sorghum": {
        "canonical": "Sorghum",
        "scientific": "Sorghum bicolor",
        "aliases": [
            "sorghum bicolor", "jowar", "milo", "great millet",
            "sorghums",
        ],
    },
    "pearl millet": {
        "canonical": "Pearl millet",
        "scientific": "Pennisetum glaucum",
        "aliases": [
            "pennisetum glaucum", "bajra", "pearl millets",
            "pennisetum americanum", "cenchrus americanus",
        ],
    },
    "finger millet": {
        "canonical": "Finger millet",
        "scientific": "Eleusine coracana",
        "aliases": [
            "eleusine coracana", "ragi", "finger millets",
        ],
    },
    "small millet": {
        "canonical": "Small millet",
        "scientific": "",
        "aliases": ["minor millets", "small millets"],
    },
    "rice": {
        "canonical": "Rice",
        "scientific": "Oryza sativa",
        "aliases": ["oryza sativa", "paddy"],
    },
    "wheat": {
        "canonical": "Wheat",
        "scientific": "Triticum aestivum",
        "aliases": ["triticum aestivum"],
    },
    "maize": {
        "canonical": "Maize",
        "scientific": "Zea mays",
        "aliases": ["corn", "zea mays"],
    },
}

# EPrints subject code → crop mapping (ICRISAT-specific)
# These codes come from the subjects field in EPrints metadata
SUBJECT_CODE_MAP = {
    "s1.1": "chickpea",
    "s1.2": "pigeonpea",
    "s1.3": "groundnut",
    "s1.4": "pearl millet",
    "s1.5": "sorghum",
    "s1.6": "finger millet",
    "s1.7": "small millet",
    "s2.1": None,  # General / Non-crop-specific
    "s2.2": None,  # Resilient Dryland Systems
    "s2.3": None,  # Markets, Institutions and Policies
    "s2.4": None,  # Grain Legumes
    "s2.5": None,  # Dryland Cereals
}

# Build reverse lookup: alias → canonical key
_ALIAS_LOOKUP: dict[str, str] = {}
for canonical_key, info in CROP_ALIASES.items():
    _ALIAS_LOOKUP[canonical_key] = canonical_key
    _ALIAS_LOOKUP[info["canonical"].lower()] = canonical_key
    if info["scientific"]:
        _ALIAS_LOOKUP[info["scientific"].lower()] = canonical_key
    for alias in info["aliases"]:
        _ALIAS_LOOKUP[alias.lower()] = canonical_key


# ──────────────────────────────────────────────────────────────────────
# Author matching
# ──────────────────────────────────────────────────────────────────────

def author_canonical_key(given: str, family: str) -> str:
    """
    Create a canonical key for an author from structured name fields.

    Examples:
        ("K", "Ravi") → "ravi_k"
        ("K.", "Ravi") → "ravi_k"
        ("Kiran", "Ravi") → "ravi_k"
        ("R K", "Varshney") → "varshney_r"
    """
    family_norm = re.sub(r'[^a-z]', '', family.lower().strip())
    given_norm = given.strip().replace(".", "").strip()

    # Take first initial only
    first_initial = given_norm[0].lower() if given_norm else "x"

    if not family_norm:
        return f"unknown_{first_initial}"

    return f"{family_norm}_{first_initial}"


def author_display_name(given: str, family: str) -> str:
    """Human-readable display name."""
    parts = [p.strip() for p in [given, family] if p.strip()]
    return " ".join(parts) if parts else "Unknown"


# ──────────────────────────────────────────────────────────────────────
# Keyword matching — 3-layer normalization
# ──────────────────────────────────────────────────────────────────────

def normalize_keyword_l1(keyword: str) -> str:
    """Layer 1: lowercase, strip, collapse whitespace."""
    return re.sub(r'\s+', ' ', keyword.lower().strip())


def normalize_keyword_l2(keyword: str) -> str:
    """Layer 2: remove hyphens, sort multi-word terms alphabetically."""
    k = normalize_keyword_l1(keyword)
    # Remove hyphens and re-collapse
    k = k.replace("-", " ")
    k = re.sub(r'\s+', ' ', k).strip()
    # Sort words for order-independent matching
    words = sorted(k.split())
    return " ".join(words)


def keyword_canonical_key(keyword: str) -> str:
    """Create canonical key for a keyword using Layer 2 normalization."""
    return normalize_keyword_l2(keyword).replace(" ", "_")


# ──────────────────────────────────────────────────────────────────────
# Crop matching
# ──────────────────────────────────────────────────────────────────────

def resolve_crop(text: str) -> dict | None:
    """
    Resolve a crop name/text to a canonical crop entry.

    Handles:
        - "s1.3" / "S1.5" (EPrints subject codes)
        - "Mandate crops > Groundnut" (EPrints subjects)
        - "Arachis hypogaea" (scientific name in abstract)
        - "peanut" / "Peanut" (common name or keyword)

    Returns dict with 'canonical', 'scientific', 'key' or None if not found.
    """
    text = text.strip()

    # Check EPrints subject codes first (s1.3, S1.5, etc.)
    code_key = text.lower()
    if code_key in SUBJECT_CODE_MAP:
        canonical_key = SUBJECT_CODE_MAP[code_key]
        if canonical_key is None:
            return None  # Non-crop subject
        info = CROP_ALIASES[canonical_key]
        return {
            "key": canonical_key,
            "canonical": info["canonical"],
            "scientific": info["scientific"],
        }

    # Extract crop name from EPrints subject format
    if ">" in text:
        text = text.split(">")[-1].strip()

    lookup_key = text.lower().strip().rstrip(".")

    if lookup_key in _ALIAS_LOOKUP:
        canonical_key = _ALIAS_LOOKUP[lookup_key]
        info = CROP_ALIASES[canonical_key]
        return {
            "key": canonical_key,
            "canonical": info["canonical"],
            "scientific": info["scientific"],
        }

    return None


# ──────────────────────────────────────────────────────────────────────
# Journal matching
# ──────────────────────────────────────────────────────────────────────

def journal_canonical_key(name: str) -> str:
    """Normalize journal name to canonical key."""
    n = name.lower().strip()
    # Remove leading "the "
    if n.startswith("the "):
        n = n[4:]
    # Collapse whitespace, remove non-alphanumeric except spaces
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', '_', n).strip("_")
    return n


# ──────────────────────────────────────────────────────────────────────
# Location matching
# ──────────────────────────────────────────────────────────────────────

# US state to country mapping
US_STATES = {
    "maine", "california", "texas", "florida", "georgia", "virginia",
    "new york", "illinois", "ohio", "pennsylvania", "michigan",
    "north carolina", "new jersey", "arizona", "washington",
    "massachusetts", "indiana", "tennessee", "missouri", "maryland",
    "wisconsin", "colorado", "minnesota", "south carolina", "alabama",
    "louisiana", "kentucky", "oregon", "oklahoma", "connecticut",
    "utah", "iowa", "nevada", "arkansas", "mississippi", "kansas",
    "nebraska", "new mexico", "idaho", "west virginia", "hawaii",
    "new hampshire", "rhode island", "montana", "delaware",
    "south dakota", "north dakota", "alaska", "vermont", "wyoming",
    "dc",
}

# Indian state/city mapping
INDIAN_LOCATIONS = {
    "delhi", "mumbai", "hyderabad", "patancheru", "bangalore",
    "chennai", "kolkata", "pune", "ahmedabad", "jaipur",
    "andhra pradesh", "telangana", "karnataka", "tamil nadu",
    "maharashtra", "rajasthan", "madhya pradesh", "uttar pradesh",
    "gujarat", "kerala", "west bengal", "bihar", "odisha",
    "jharkhand", "chhattisgarh", "punjab", "haryana",
}


def normalize_location(name: str) -> dict:
    """
    Normalize a location name and determine its type.
    Returns dict with 'key', 'display', 'type', 'parent_country'.
    """
    n = name.lower().strip()

    loc_type = "location"
    parent_country = None

    if n in US_STATES:
        loc_type = "state"
        parent_country = "usa"
    elif n in INDIAN_LOCATIONS:
        loc_type = "state_city"
        parent_country = "india"
    elif n in ("usa", "us", "united states", "united states of america"):
        n = "usa"
        loc_type = "country"
    elif n in ("uk", "united kingdom", "great britain"):
        n = "uk"
        loc_type = "country"
    else:
        loc_type = "country"

    return {
        "key": re.sub(r'[^a-z0-9]', '_', n),
        "display": name.strip().title(),
        "type": loc_type,
        "parent_country": parent_country,
    }


# ──────────────────────────────────────────────────────────────────────
# Funder matching
# ──────────────────────────────────────────────────────────────────────

# Common funder name normalizations
FUNDER_ALIASES = {
    "icrisat": "ICRISAT",
    "cgiar": "CGIAR",
    "consultative group for international agricultural research(cgiar)": "CGIAR",
    "consultative group for international agricultural research (cgiar)": "CGIAR",
    "indian council of agricultural research": "ICAR",
    "icar": "ICAR",
    "department of biotechnology": "DBT India",
    "government of india - department of biotechnology": "DBT India",
    "department of science and technology": "DST India",
    "government of india - department of science and technology": "DST India",
    "bill and melinda gates foundation": "Gates Foundation",
    "bmgf": "Gates Foundation",
    "usaid": "USAID",
    "world bank": "World Bank",
}


def funder_canonical_key(name: str) -> str:
    """Normalize funder name to canonical key."""
    n = name.lower().strip()
    if n in FUNDER_ALIASES:
        return re.sub(r'[^a-z0-9]', '_', FUNDER_ALIASES[n].lower())

    # Generic normalization
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', '_', n).strip("_")
    return n


def funder_display_name(name: str) -> str:
    """Get display name for a funder."""
    n = name.lower().strip()
    if n in FUNDER_ALIASES:
        return FUNDER_ALIASES[n]
    return name.strip()


# ──────────────────────────────────────────────────────────────────────
# Generic topic/agrotag normalization
# ──────────────────────────────────────────────────────────────────────

def topic_canonical_key(name: str) -> str:
    """Normalize a topic/agrotag to canonical key."""
    n = name.lower().strip()
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', '_', n).strip("_")
    return n


# ──────────────────────────────────────────────────────────────────────
# Batch deduplication helpers
# ──────────────────────────────────────────────────────────────────────

class NodeRegistry:
    """
    Central registry for deduplicating nodes across all papers.
    Tracks canonical keys → node data, and records all variants.
    """

    def __init__(self):
        # {node_type: {canonical_key: node_dict}}
        self.nodes: dict[str, dict[str, dict]] = defaultdict(dict)
        # {node_type: {canonical_key: set_of_variants}}
        self.variants: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
        # Auto-increment ID per type
        self._counters: dict[str, int] = defaultdict(int)

    def _next_id(self, node_type: str) -> str:
        self._counters[node_type] += 1
        return f"{node_type}_{self._counters[node_type]}"

    def add_author(self, given: str, family: str) -> str:
        """Register an author, return the node ID."""
        key = author_canonical_key(given, family)
        display = author_display_name(given, family)

        if key not in self.nodes["author"]:
            self.nodes["author"][key] = {
                "id": self._next_id("author"),
                "type": "AUTHOR",
                "key": key,
                "display_name": display,
                "given": given,
                "family": family,
            }
        self.variants["author"][key].add(display)
        return self.nodes["author"][key]["id"]

    def add_keyword(self, raw_keyword: str) -> str:
        """Register a keyword, return the node ID."""
        key = keyword_canonical_key(raw_keyword)
        display = raw_keyword.strip()

        if not key:
            return ""

        if key not in self.nodes["keyword"]:
            self.nodes["keyword"][key] = {
                "id": self._next_id("keyword"),
                "type": "KEYWORD",
                "key": key,
                "display_name": display,
            }
        self.variants["keyword"][key].add(display)
        return self.nodes["keyword"][key]["id"]

    def add_crop(self, raw_text: str) -> str | None:
        """Register a crop from subject text, return node ID or None."""
        resolved = resolve_crop(raw_text)
        if not resolved:
            return None

        key = resolved["key"]
        if key not in self.nodes["crop"]:
            self.nodes["crop"][key] = {
                "id": self._next_id("crop"),
                "type": "CROP",
                "key": key,
                "display_name": resolved["canonical"],
                "scientific_name": resolved["scientific"],
            }
        self.variants["crop"][key].add(raw_text.strip())
        return self.nodes["crop"][key]["id"]

    def add_topic(self, raw_topic: str) -> str:
        """Register a topic/agrotag, return node ID."""
        key = topic_canonical_key(raw_topic)
        display = raw_topic.strip().lower()

        if not key:
            return ""

        if key not in self.nodes["topic"]:
            self.nodes["topic"][key] = {
                "id": self._next_id("topic"),
                "type": "TOPIC",
                "key": key,
                "display_name": display,
            }
        self.variants["topic"][key].add(display)
        return self.nodes["topic"][key]["id"]

    def add_journal(self, raw_name: str) -> str:
        """Register a journal, return node ID."""
        key = journal_canonical_key(raw_name)
        display = raw_name.strip()

        if not key:
            return ""

        if key not in self.nodes["journal"]:
            self.nodes["journal"][key] = {
                "id": self._next_id("journal"),
                "type": "JOURNAL",
                "key": key,
                "display_name": display,
            }
        self.variants["journal"][key].add(display)
        return self.nodes["journal"][key]["id"]

    def add_location(self, raw_name: str) -> str:
        """Register a geographic location, return node ID."""
        loc = normalize_location(raw_name)
        key = loc["key"]

        if not key:
            return ""

        if key not in self.nodes["location"]:
            self.nodes["location"][key] = {
                "id": self._next_id("location"),
                "type": "LOCATION",
                "key": key,
                "display_name": loc["display"],
                "location_type": loc["type"],
                "parent_country": loc["parent_country"],
            }
        self.variants["location"][key].add(raw_name.strip())
        return self.nodes["location"][key]["id"]

    def add_funder(self, raw_name: str) -> str:
        """Register a funder, return node ID."""
        key = funder_canonical_key(raw_name)
        display = funder_display_name(raw_name)

        if not key:
            return ""

        if key not in self.nodes["funder"]:
            self.nodes["funder"][key] = {
                "id": self._next_id("funder"),
                "type": "FUNDER",
                "key": key,
                "display_name": display,
            }
        self.variants["funder"][key].add(raw_name.strip())
        return self.nodes["funder"][key]["id"]

    def add_llm_entity(self, entity_type: str, raw_name: str) -> str:
        """Register an LLM-extracted entity (Method, Trait, Gene, Condition)."""
        key = topic_canonical_key(raw_name)

        if not key:
            return ""

        type_key = entity_type.lower()
        if key not in self.nodes[type_key]:
            self.nodes[type_key][key] = {
                "id": self._next_id(type_key),
                "type": entity_type,
                "key": key,
                "display_name": raw_name.strip(),
            }
        self.variants[type_key][key].add(raw_name.strip())
        return self.nodes[type_key][key]["id"]

    def get_all_nodes(self) -> list[dict]:
        """Return all registered nodes as a flat list."""
        result = []
        for type_nodes in self.nodes.values():
            for node in type_nodes.values():
                result.append(node)
        return result

    def get_stats(self) -> dict:
        """Return counts per node type."""
        return {ntype: len(nodes) for ntype, nodes in self.nodes.items()}
