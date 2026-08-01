"""Consistent success/failure response envelope for the /api/v1/* surface.

Every /api/v1 endpoint returns one of:
  Success: {"success": true,  "message": "...", "data": {...}}
  Failure: {"success": false, "message": "...", "errors": [...]}

Plain dict-returning helpers are used (rather than a generic Pydantic response_model)
so routers stay simple - FastAPI still serializes the nested Pydantic schemas via
``.model_dump(mode="json")`` before they're wrapped here.
"""

from typing import Any, List, Optional


def success_envelope(data: Any, message: str = "OK") -> dict:
    return {"success": True, "message": message, "data": data}


def error_envelope(message: str, errors: Optional[List[str]] = None) -> dict:
    return {"success": False, "message": message, "errors": errors or [message]}
