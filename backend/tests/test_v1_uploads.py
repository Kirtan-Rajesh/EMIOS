"""Tests for the /api/v1 Document Upload module (upload a real file / list uploads).

Uploads are multipart/form-data now (a real file, not a JSON metadata stub) -
see app/api/v1/uploads.py. Embeddings/vector storage fall back to the
deterministic local embedder + in-memory vector store in this test environment
(no AWS credentials, no live Qdrant reachable from the SQLite-only test DB
override), so these tests check the pipeline's plumbing (status transitions,
chunk counts, storage_reference format) rather than semantic search quality.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def _create_assessment(client) -> str:
    resp = await client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    return resp.json()["data"]["assessment_id"]


async def test_upload_text_document_happy_path(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("runbook.txt", b"This system handles order processing " * 100, "text/plain")},
        data={"source_type": "manual"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["assessment_id"] == assessment_id
    assert data["filename"] == "runbook.txt"
    assert data["content_type"] == "text/plain"
    assert data["source_type"] == "manual"
    assert data["status"] == "processed"
    assert data["chunk_count"] >= 1
    assert isinstance(data["upload_id"], str) and data["upload_id"]
    assert "uploaded_at" in data


async def test_upload_xlsx_document_happy_path(v1_client):
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["System ID", "System Name", "Category"])
    ws.append(["order_svc", "Order Service", "Microservice"])
    buf = io.BytesIO()
    wb.save(buf)

    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={
            "file": (
                "Application_Metadata_Catalog.xlsx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"source_type": "manual"},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["filename"] == "Application_Metadata_Catalog.xlsx"
    assert data["status"] == "processed"
    # Sheet name header + 2 rows of tab-joined cell text is well under the 1500-char
    # chunk size, so this should land in exactly one chunk (mirrors the pptx/docx
    # "small document -> 1 chunk" behavior already implied by the >=1 assertions above).
    assert data["chunk_count"] == 1


async def test_upload_rejects_unsupported_extension(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("dump.sql", b"CREATE TABLE foo (id INT);", "application/sql")},
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


async def test_upload_empty_file_zero_chunks(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("empty.txt", b"   \n  ", "text/plain")},
        data={"source_type": "manual"},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "processed"
    assert data["chunk_count"] == 0


async def test_upload_default_source_type(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("notes.txt", b"some notes about the migration", "text/plain")},
    )

    assert response.status_code == 201
    assert response.json()["data"]["source_type"] == "manual"


async def test_upload_nonexistent_assessment(v1_client):
    response = await v1_client.post(
        "/api/v1/assessments/does-not-exist/uploads",
        files={"file": ("a.txt", b"content", "text/plain")},
    )

    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_upload_missing_file(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/uploads")
    assert response.status_code == 422


async def test_list_uploads_happy_path(v1_client):
    assessment_id = await _create_assessment(v1_client)
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("a.txt", b"content about system A migration plan", "text/plain")},
    )
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("b.txt", b"content about system B dependency notes", "text/plain")},
    )

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/uploads")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]) == 2
    filenames = {u["filename"] for u in body["data"]}
    assert filenames == {"a.txt", "b.txt"}
    for upload in body["data"]:
        assert upload["chunk_count"] >= 1


async def test_list_uploads_empty(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/uploads")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == []


async def test_list_uploads_nonexistent_assessment(v1_client):
    response = await v1_client.get("/api/v1/assessments/does-not-exist/uploads")

    assert response.status_code == 404
    assert response.json()["success"] is False


def _make_zip(entries: dict) -> bytes:
    """Builds an in-memory zip archive from {path_in_archive: bytes_content}."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return buf.getvalue()


async def test_upload_zip_extracts_and_processes_members(v1_client):
    assessment_id = await _create_assessment(v1_client)
    archive = _make_zip(
        {
            "runbook.txt": b"This system handles order processing " * 50,
            "notes/architecture.md": b"# Architecture\nSome notes about the system.",
            "dump.sql": b"CREATE TABLE foo (id INT);",  # unsupported extension
        }
    )

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads/zip",
        files={"file": ("docs.zip", archive, "application/zip")},
        data={"source_type": "manual"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["extracted_count"] == 2
    filenames = {u["filename"] for u in data["uploads"]}
    assert filenames == {"runbook.txt", "architecture.md"}
    for upload in data["uploads"]:
        assert upload["assessment_id"] == assessment_id
        assert upload["status"] == "processed"
        assert upload["chunk_count"] >= 1
    assert len(data["skipped"]) == 1
    assert data["skipped"][0]["filename"] == "dump.sql"

    list_response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/uploads")
    assert len(list_response.json()["data"]) == 2


async def test_upload_zip_ignores_macos_sidecar_files(v1_client):
    assessment_id = await _create_assessment(v1_client)
    archive = _make_zip(
        {
            "notes.txt": b"real content about the migration plan",
            "__MACOSX/._notes.txt": b"resource fork junk",
            ".DS_Store": b"finder metadata",
        }
    )

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads/zip",
        files={"file": ("docs.zip", archive, "application/zip")},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["extracted_count"] == 1
    assert data["uploads"][0]["filename"] == "notes.txt"
    assert data["skipped"] == []


async def test_upload_zip_rejects_non_zip_extension(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads/zip",
        files={"file": ("notes.txt", b"not a zip", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


async def test_upload_zip_rejects_corrupt_archive(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads/zip",
        files={"file": ("docs.zip", b"this is not actually a zip file", "application/zip")},
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


async def test_upload_zip_rejects_too_many_members(v1_client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MAX_ZIP_MEMBERS", 2)
    assessment_id = await _create_assessment(v1_client)
    archive = _make_zip({f"file_{i}.txt": b"content" for i in range(3)})

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads/zip",
        files={"file": ("docs.zip", archive, "application/zip")},
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


async def test_upload_zip_nonexistent_assessment(v1_client):
    archive = _make_zip({"notes.txt": b"content"})

    response = await v1_client.post(
        "/api/v1/assessments/does-not-exist/uploads/zip",
        files={"file": ("docs.zip", archive, "application/zip")},
    )

    assert response.status_code == 404
    assert response.json()["success"] is False
