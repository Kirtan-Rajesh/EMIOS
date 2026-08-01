"""Service layer for the /api/v1/* surface: all business logic lives here.
Routers only do request validation / DI / response shaping; repositories only do
DB access. Kept separate from the legacy app/services package (Neo4j/simulation)."""
