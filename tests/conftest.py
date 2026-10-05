import os, shutil, pytest
RAW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")

@pytest.fixture(scope="session")
def real_env(tmp_path_factory):
    """Full ingestion of the REAL dataset into a temp DB."""
    from src.ingest import IngestionPipeline
    from src.database import DatabaseManager
    from src.retrieval.index import HybridIndex
    from src.qa.engine import QAEngine
    d = tmp_path_factory.mktemp("real")
    db_path = str(d / "t.db")
    stats = IngestionPipeline(db_path, str(d / "log.txt")).run(RAW)
    db = DatabaseManager(db_path)
    ix = HybridIndex(db, str(d / "ix.pkl"))
    return {"db": db, "stats": stats, "index": ix, "engine": QAEngine(db, ix), "db_path": db_path, "dir": d}
