import os
import networkx as nx
import re
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"
INPUT_GRAPH = DATA_DIR / "graph_jobs.graphml"
OUTPUT_GRAPH = DATA_DIR / "graph_jobs_enriched.graphml"


def clean_label(value: str) -> str:
    if not isinstance(value, str):
        return "Unknown"
    value = value.strip()
    if not value or value.lower() == "nan":
        return "Unknown"
    return value


def enrich_graph(input_path=None, output_path=None, with_ontology=True):
    if input_path is None:
        input_path = INPUT_GRAPH
    if output_path is None:
        output_path = OUTPUT_GRAPH

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input graph not found: {input_path}")

    G = nx.read_graphml(str(input_path))
    print(f"[OK] Loaded graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    original_node_count = G.number_of_nodes()

    seen_companies = set()
    seen_locations = set()
    seen_levels = set()
    seen_types = set()

    job_nodes = [(n, d) for n, d in G.nodes(data=True) if d.get("type") == "job"]

    new_nodes = []
    new_edges = []

    for node_id, data in job_nodes:

        # --- Company ---
        company = clean_label(data.get("company", ""))
        if company and company not in seen_companies:
            company_id = f"company_{company.lower().replace(' ', '_')}"
            G.add_node(company_id, type="company", label=company)
            seen_companies.add(company)
            new_nodes.append(company_id)

        company_id = f"company_{company.lower().replace(' ', '_')}"
        if not G.has_edge(company_id, node_id):
            G.add_edge(company_id, node_id, relation="OPENS")
            new_edges.append((company_id, node_id))

        # --- Location ---
        location = clean_label(data.get("job_location", ""))
        if location and location not in seen_locations:
            loc_id = f"location_{location.lower().replace(' ', '_').replace(',', '')}"
            G.add_node(loc_id, type="location", label=location)
            seen_locations.add(location)
            new_nodes.append(loc_id)

        loc_id = f"location_{location.lower().replace(' ', '_').replace(',', '')}"
        if not G.has_edge(node_id, loc_id):
            G.add_edge(node_id, loc_id, relation="LOCATED_IN")
            new_edges.append((node_id, loc_id))

        # --- Job Level ---
        level = clean_label(data.get("job_level", ""))
        if level and level not in seen_levels:
            level_id = f"level_{level.lower().replace(' ', '_')}"
            G.add_node(level_id, type="level", label=level)
            seen_levels.add(level)
            new_nodes.append(level_id)

        level_id = f"level_{level.lower().replace(' ', '_')}"
        if not G.has_edge(node_id, level_id):
            G.add_edge(node_id, level_id, relation="HAS_LEVEL")
            new_edges.append((node_id, level_id))

        # --- Job Type ---
        job_type = clean_label(data.get("job_type", ""))
        if job_type and job_type not in seen_types:
            type_id = f"jobtype_{job_type.lower().replace(' ', '_')}"
            G.add_node(type_id, type="jobtype", label=job_type)
            seen_types.add(job_type)
            new_nodes.append(type_id)

        type_id = f"jobtype_{job_type.lower().replace(' ', '_')}"
        if not G.has_edge(node_id, type_id):
            G.add_edge(node_id, type_id, relation="HAS_TYPE")
            new_edges.append((node_id, type_id))

    # --- Ontology-based enrichment (Tahap 1) ---
    if with_ontology:
        try:
            from src.ontology_service import get_ontology, enrich_graph_with_ontology
            ontology = get_ontology()
            enrich_graph_with_ontology(G, ontology)
        except Exception as e:
            print(f"[!] Ontology enrichment skipped: {e}")

    # Save enriched graph
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(G, str(output_path))
    print(f"[OK] Enriched graph saved: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    total_new = G.number_of_nodes() - original_node_count
    print(f"     New nodes added: {total_new}")
    print(f"     Companies: {len(seen_companies)}, Locations: {len(seen_locations)}, Levels: {len(seen_levels)}, Types: {len(seen_types)}")

    return G


def load_enriched_graph(path=None):
    if path is None:
        path = OUTPUT_GRAPH
    if not os.path.exists(path):
        print(f"[!] Enriched graph not found at {path}, generating...")
        enrich_graph(output_path=path)

    G = nx.read_graphml(str(path))
    print(f"[OK] Loaded enriched graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


if __name__ == "__main__":
    enrich_graph()
