"""SQLAlchemy ORM entities for the relational persistence layer.

Importing this package (as ``main.py`` and ``backend/tests/conftest.py`` both do)
registers every entity on the shared ``app.db.base.Base`` metadata, which is a
prerequisite for ``Base.metadata.create_all`` to create all tables rather than
only whichever entity module happened to be imported first.
"""

from app.entities.user import User
from app.entities.assessment import Assessment
from app.entities.upload import AssessmentUpload
from app.entities.wave import MigrationWave
from app.entities.graph import AssessmentEdge, AssessmentNode
from app.entities.simulation import AssessmentSimulation
from app.entities.agent_run import AgentRun
from app.entities.report import AssessmentReport, ReportRevision
from app.entities.document_chunk import DocumentChunk

__all__ = [
    "User",
    "Assessment",
    "AssessmentUpload",
    "MigrationWave",
    "AssessmentNode",
    "AssessmentEdge",
    "AssessmentSimulation",
    "AgentRun",
    "AssessmentReport",
    "ReportRevision",
    "DocumentChunk",
]
