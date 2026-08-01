import logging
from app.core.config import settings

logger = logging.getLogger("emios")

# Global clients
neo4j_driver = None
qdrant_client = None

try:
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False

try:
    from qdrant_client import QdrantClient
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

def init_db():
    global neo4j_driver, qdrant_client
    
    # Initialize Neo4j
    if HAS_NEO4J:
        try:
            neo4j_driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            )
            # Verify connectivity
            neo4j_driver.verify_connectivity()
            logger.info("Successfully connected to Neo4j database.")
        except Exception as e:
            logger.warning(f"Could not connect to Neo4j database at {settings.NEO4J_URI}: {e}. Graph features will run in mock/local-fallback mode.")
            neo4j_driver = None
    else:
        logger.warning("neo4j driver not installed. Graph database features will run in local-fallback mode.")
        neo4j_driver = None

    # Initialize Qdrant
    if HAS_QDRANT:
        try:
            qdrant_client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                timeout=5.0
            )
            # Check connection
            qdrant_client.get_collections()
            logger.info("Successfully connected to Qdrant vector database.")
        except Exception as e:
            logger.warning(f"Could not connect to Qdrant at {settings.QDRANT_HOST}:{settings.QDRANT_PORT}: {e}. Semantic Search will run in fallback mode.")
            qdrant_client = None
    else:
        logger.warning("qdrant-client not installed. Semantic Search features will run in fallback mode.")
        qdrant_client = None

def close_db():
    global neo4j_driver
    if neo4j_driver:
        try:
            neo4j_driver.close()
            logger.info("Neo4j driver connection closed.")
        except Exception:
            pass
