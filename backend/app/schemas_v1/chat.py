"""Pydantic v2 schemas for the per-assessment Document-grounded Chat module."""

from typing import List, Optional

from pydantic import BaseModel


class ChatMessageIn(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessageIn]


class ChatResponse(BaseModel):
    reply: str
    trace_id: Optional[str] = None
    # Upload IDs whose document chunks were actually retrieved and used to
    # ground this reply - empty if nothing relevant was found (or nothing's
    # been discovered/uploaded yet). Lets a UI show "grounded in N documents".
    sources: List[str] = []
