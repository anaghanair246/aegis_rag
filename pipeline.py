"""CLI: python pipeline.py [raw_dir]  -> ingest + build knowledge layer + (re)build index."""
import json, sys
from src import config
from src.ingest import IngestionPipeline

if __name__ == "__main__":
    raw = sys.argv[1] if len(sys.argv) > 1 else config.RAW_DIR
    stats = IngestionPipeline().run(raw)
    from src.database import DatabaseManager
    from src.retrieval.index import HybridIndex
    HybridIndex(DatabaseManager(config.DB_PATH)).rebuild()
    print(json.dumps({k: v for k, v in stats.items() if k != "per_file_seconds"}, indent=2))
