"""Traffic Law GraphRAG FastAPI package."""

from src.api.main import app, create_app

__version__ = "1.0.0"
__all__ = ["__version__", "app", "create_app"]
