"""Tests for XLSX support in the Document Discovery structured extractors
(MetadataExtractor, EtlMappingExtractor) - see app/services_v1/extraction/base.py's
read_tabular_rows/sniff_header_line, which let CSV and XLSX share one row-reading
path. XLSX text extraction for RAG (DocumentProcessingService) is exercised via
the upload endpoint tests instead (tests/test_v1_uploads.py).
"""

import io

from openpyxl import Workbook

from app.services_v1.extraction.document_extraction_service import DocumentExtractionService
from app.services_v1.extraction.etl_mapping_extractor import EtlMappingExtractor
from app.services_v1.extraction.metadata_extractor import MetadataExtractor


def _xlsx_bytes(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_metadata_extractor_can_handle_xlsx():
    content = _xlsx_bytes(
        ["System ID", "System Name", "Category", "Priority", "Migration Complexity", "Runtime", "Annual Hosting Cost ($)"],
        [["order_svc", "Order Service", "Microservice", "High", "Medium", "Java 17", "95000"]],
    )
    extractor = MetadataExtractor()
    assert extractor.can_handle("Application_Metadata_Catalog.xlsx", "", content) is True


def test_metadata_extractor_rejects_unrelated_xlsx():
    content = _xlsx_bytes(["Hostname", "IP Address", "Datacenter"], [["srv01", "10.0.0.1", "DC1"]])
    extractor = MetadataExtractor()
    assert extractor.can_handle("CMDB_Export_Servers.xlsx", "", content) is False


def test_metadata_extractor_extracts_nodes_from_xlsx():
    content = _xlsx_bytes(
        ["System ID", "System Name", "Category", "Priority", "Migration Complexity", "Runtime", "Annual Hosting Cost ($)"],
        [
            ["order_svc", "Order Service", "Microservice", "High", "Medium", "Java 17", "95000"],
            ["orders_db", "Orders Database", "Database", "Critical", "Low", "PostgreSQL 15", "40000"],
        ],
    )
    extractor = MetadataExtractor()
    result = extractor.extract("Application_Metadata_Catalog.xlsx", content, "")

    assert result.confidence == 1.0
    assert len(result.nodes) == 2
    by_id = {n.id: n for n in result.nodes}
    assert by_id["order_svc"].name == "Order Service"
    assert by_id["order_svc"].business_value == "High"
    assert by_id["order_svc"].annual_cost == 95000.0
    assert by_id["orders_db"].business_value == "High"  # "Critical" normalizes to "High"


def test_etl_mapping_extractor_can_handle_xlsx():
    content = _xlsx_bytes(
        ["Source System", "Target System", "Connection Type", "Importance"],
        [["Order Service", "Inventory Service", "Sync", "High"]],
    )
    extractor = EtlMappingExtractor()
    assert extractor.can_handle("System_Dependency_Mapping.xlsx", "", content) is True


def test_etl_mapping_extractor_extracts_edges_from_xlsx():
    content = _xlsx_bytes(
        ["Source System", "Target System", "Connection Type", "Importance"],
        [
            ["Order Service", "Inventory Service", "Sync", "High"],
            ["Order Service", "Orders Database", "DB", "Critical"],
        ],
    )
    extractor = EtlMappingExtractor()
    result = extractor.extract("System_Dependency_Mapping.xlsx", content, "")

    assert result.confidence == 1.0
    assert len(result.edges) == 2
    assert len(result.nodes) == 3  # Order Service, Inventory Service, Orders Database
    edge_pairs = {(e.source, e.target) for e in result.edges}
    assert ("order_service", "inventory_service") in edge_pairs
    assert ("order_service", "orders_database") in edge_pairs


def test_document_extraction_service_merges_xlsx_metadata_and_mapping():
    metadata_xlsx = _xlsx_bytes(
        ["System ID", "System Name", "Category", "Priority", "Migration Complexity", "Runtime", "Annual Hosting Cost ($)"],
        [
            ["order_svc", "Order Service", "Microservice", "High", "Medium", "Java 17", "95000"],
            ["inventory_svc", "Inventory Service", "Microservice", "High", "Medium", "Java 17", "80000"],
        ],
    )
    mapping_xlsx = _xlsx_bytes(
        ["Source System", "Target System", "Connection Type", "Importance"],
        [["Order Service", "Inventory Service", "Sync", "High"]],
    )

    service = DocumentExtractionService()
    nodes, edges, warnings, report = service.extract_documents(
        [
            ("Application_Metadata_Catalog.xlsx", metadata_xlsx),
            ("System_Dependency_Mapping.xlsx", mapping_xlsx),
        ]
    )

    # The richer MetadataExtractor nodes (real type/runtime/cost) win the merge
    # over EtlMappingExtractor's generic placeholders for the same two systems.
    assert len(nodes) == 2
    order_node = next(n for n in nodes if n.name == "Order Service")
    assert order_node.runtime == "Java 17"
    assert order_node.annual_cost == 95000.0

    assert len(edges) == 1
    assert edges[0].source == order_node.id
    assert report["overall_confidence"] == 1.0
