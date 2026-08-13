import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.scripts.download_onet import run as run_onet
from src.scripts.download_esco import run as run_esco
from src.ontology_service import get_ontology, enrich_graph_with_ontology
from src.graph_enricher import load_enriched_graph


def step(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run O*NET/ESCO ontology pipeline")
    parser.add_argument("--force-download", action="store_true", help="Force re-download of datasets")
    parser.add_argument("--skip-onet", action="store_true", help="Skip O*NET download")
    parser.add_argument("--skip-esco", action="store_true", help="Skip ESCO download")
    parser.add_argument("--skip-graph", action="store_true", help="Skip graph enrichment")
    args = parser.parse_args()

    if not args.skip_onet:
        step("1/4: Downloading and parsing O*NET database")
        try:
            run_onet(force_download=args.force_download)
        except Exception as e:
            print(f"[!] O*NET step failed (continuing): {e}")
    else:
        print("[SKIP] O*NET download")

    if not args.skip_esco:
        step("2/4: Downloading and parsing ESCO dataset")
        try:
            run_esco(force_download=args.force_download)
        except Exception as e:
            print(f"[!] ESCO step failed (continuing): {e}")
    else:
        print("[SKIP] ESCO download")

    step("3/4: Loading ontology with external sources")
    svc = get_ontology(refresh=True)
    ext_names = list(svc.external_sources.keys())
    if ext_names:
        print(f"[OK] External ontologies loaded: {', '.join(ext_names)}")
    else:
        print("[!] No external ontologies loaded")

    print(f"  job_to_skills entries: {len(svc.ontology.get('job_to_skills', {}))}")
    print(f"  all_skill_names: {len(svc.ontology.get('all_skill_names', []))}")
    print(f"  skill_relations related_to: {len(svc.ontology.get('skill_relations', {}).get('related_to', []))}")

    test_titles = [
        "Software Engineer", "Data Scientist", "Registered Nurse",
        "Accountant", "Project Manager", "Teacher",
        "Mechanical Engineer", "Pharmacist",
    ]
    for t in test_titles:
        skills = svc.get_skills_for_job(t)
        print(f"  {t}: {len(skills)} skills")

    if not args.skip_graph:
        step("4/4: Re-enriching knowledge graph with external ontology")
        graph_path = Path(__file__).parent.parent / "data" / "graph_jobs_enriched.graphml"
        if graph_path.exists():
            backup = graph_path.with_suffix(".graphml.bak")
            if not backup.exists():
                import shutil
                shutil.copy2(graph_path, backup)
                print(f"[OK] Backed up existing graph to {backup}")
        try:
            G = load_enriched_graph()
            enrich_graph_with_ontology(G, svc)
            output = graph_path
            import networkx as nx
            nx.write_graphml(G, str(output))
            print(f"[OK] Re-enriched graph saved to {output}")
            print(f"  Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")
        except Exception as e:
            print(f"[!] Graph enrichment failed: {e}")

    step("Done! Ontology pipeline complete.")
    print(f"\nSummary:")
    print(f"  O*NET: {'OK' if not args.skip_onet else 'SKIPPED'}")
    print(f"  ESCO:  {'OK' if not args.skip_esco else 'SKIPPED'}")
    print(f"  Graph: {'OK' if not args.skip_graph else 'SKIPPED'}")
    print(f"  Total job mappings: {len(svc.ontology.get('job_to_skills', {}))}")


if __name__ == "__main__":
    main()
