"""Tests for the semantic entity-resolution tier added on top of the existing
exact-name matching in app/services_v1/extraction/entity_resolution.py: two
generic candidate-generation heuristics (embedding-name similarity above
settings.ENTITY_RESOLUTION_CANDIDATE_SIMILARITY_FLOOR, and lexical token-
subset matching) that only decide what's worth asking an LLM about - actual
merges always require an explicit LLM confirmation, never a bare heuristic
score, however high. Also covers graceful degradation when embeddings/LLM
aren't usable.

Embeddings/LLM calls are monkeypatched at their origin modules
(app.core.embeddings.get_embedding_provider / app.core.llm_provider.
invoke_with_fallback) rather than mocked at the entity_resolution import site,
since entity_resolution.py imports them lazily inside the functions that use
them - patching the origin is what actually takes effect.
"""

import json
import math

import pytest

from app.models.schemas import DependencyEdge, ServiceNode
from app.services_v1.extraction.base import ExtractionResult
from app.services_v1.extraction.entity_resolution import (
    _RECONCILIATION_BATCH_SIZE,
    _reconcile_all_candidates,
    merge_extraction_results,
)


def _vec(angle_deg: float) -> list:
    """A 2D unit vector at `angle_deg` from the reference (0deg) vector -
    gives exact, easy-to-reason-about cosine similarity: cos(angle_deg)."""
    theta = math.radians(angle_deg)
    return [math.cos(theta), math.sin(theta)]


class _StubEmbeddingProvider:
    """embed() looks up a pre-assigned vector by node name; raises for any
    name it wasn't told about, so a test can't accidentally pass by silently
    embedding something unexpected."""

    def __init__(self, vectors_by_name: dict):
        self._vectors = vectors_by_name

    def embed(self, text: str):
        return self._vectors[text]


def _node(node_id: str, name: str, node_type: str = "Microservice") -> ServiceNode:
    return ServiceNode(id=node_id, name=name, type=node_type)


def _result(extractor: str, nodes=(), edges=(), confidence: float = 1.0, filename: str = "") -> ExtractionResult:
    return ExtractionResult(
        source_filename=filename or f"{extractor}.file", extractor=extractor, nodes=list(nodes), edges=list(edges),
        confidence=confidence,
    )


def test_exact_match_merges_without_touching_embeddings(monkeypatch):
    def _boom():
        raise AssertionError("embedding provider should not be constructed for an exact-key match")

    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", _boom)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Order Service", "Microservice")]),
        _result("LlmPromptExtractor", nodes=[_node("order_service", "order-service")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 1
    assert nodes[0].id == "app_1"  # higher-priority extractor's id survives
    assert any("Merged 2 references" in w for w in warnings)


def test_semantic_merge_disabled_skips_embedding_entirely(monkeypatch):
    def _boom():
        raise AssertionError("embedding provider should not be constructed when enable_semantic_merge=False")

    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", _boom)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Redis Cache Cluster", "Database")]),
        _result("LlmPromptExtractor", nodes=[_node("redis", "Redis")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results, enable_semantic_merge=False)

    assert len(nodes) == 2  # no exact-key match, and semantic merge is off - stays separate


def test_no_similarity_score_ever_bypasses_llm_confirmation(monkeypatch):
    """There is deliberately no threshold high enough to skip the LLM: even a
    near-identical embedding (cos(1deg) ~= 0.9998) plus a lexical-subset match
    must still go through reconciliation, and if the LLM says "different",
    the nodes stay separate. Proves there's no numeric shortcut baked in
    anywhere for merging - only an explicit LLM "yes" ever does."""
    vectors = {"System A": _vec(0), "System A Prime": _vec(1)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))

    calls = []

    def _fake_invoke(system_prompt, user_prompt, agent_name, fallback_response):
        calls.append(user_prompt)
        return json.dumps({"decisions": [{"index": 0, "same_system": False, "reason": "actually unrelated"}]})

    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", _fake_invoke)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "System A", "Microservice")]),
        _result("LlmPromptExtractor", nodes=[_node("sys_a_prime", "System A Prime")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(calls) == 1  # the LLM was actually consulted, not bypassed
    assert len(nodes) == 2  # and its "different" verdict was respected


def test_ambiguous_pair_merges_when_llm_confirms_same_system(monkeypatch):
    vectors = {"Payment Service": _vec(0), "PaySvc": _vec(35)}  # cos(35deg) ~= 0.819, ambiguous band
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))

    def _fake_invoke(system_prompt, user_prompt, agent_name, fallback_response):
        assert agent_name == "Entity Reconciliation Agent"
        assert "PaySvc" in user_prompt and "Payment Service" in user_prompt
        return json.dumps({"decisions": [{"index": 0, "same_system": True, "reason": "same system, different casing"}]})

    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", _fake_invoke)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Payment Service", "Microservice")]),
        _result("LlmPromptExtractor", nodes=[_node("paysvc", "PaySvc")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 1
    assert nodes[0].id == "app_1"
    assert any("LLM-confirmed" in w for w in warnings)


def test_ambiguous_pair_stays_separate_when_llm_says_different(monkeypatch):
    vectors = {"Finance Consolidation & Close": _vec(0), "Finance": _vec(35)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))

    def _fake_invoke(system_prompt, user_prompt, agent_name, fallback_response):
        return json.dumps({"decisions": [{"index": 0, "same_system": False, "reason": "too vague to conflate"}]})

    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", _fake_invoke)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Finance Consolidation & Close", "Microservice")]),
        _result("LlmPromptExtractor", nodes=[_node("finance", "Finance")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 2
    assert {n.id for n in nodes} == {"app_1", "finance"}


def test_ambiguous_pair_stays_separate_when_llm_unavailable(monkeypatch):
    """invoke_with_fallback()'s real behavior when no provider is configured:
    returns the caller-supplied fallback_response verbatim. For entity
    reconciliation that fallback is '{"decisions": []}' - must be treated as
    "nothing confirmed", not as an error, and must not merge anything."""
    vectors = {"Payment Service": _vec(0), "PaySvc": _vec(35)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))

    def _fake_invoke(system_prompt, user_prompt, agent_name, fallback_response):
        return fallback_response  # simulates "no LLM provider configured"

    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", _fake_invoke)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Payment Service", "Microservice")]),
        _result("LlmPromptExtractor", nodes=[_node("paysvc", "PaySvc")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 2


def test_malformed_llm_response_does_not_crash_and_does_not_merge(monkeypatch):
    vectors = {"Payment Service": _vec(0), "PaySvc": _vec(35)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))
    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", lambda *a, **k: "not json at all")

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Payment Service", "Microservice")]),
        _result("LlmPromptExtractor", nodes=[_node("paysvc", "PaySvc")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 2


def test_embedding_provider_failure_degrades_to_exact_match_only(monkeypatch):
    def _boom():
        raise RuntimeError("no AWS credentials")

    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", _boom)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Redis Cache Cluster", "Database")]),
        _result("LlmPromptExtractor", nodes=[_node("redis", "Redis")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 2  # no crash, just no semantic merge
    assert any("Semantic entity resolution skipped" in w for w in warnings)


def test_semantic_merge_remaps_edges_to_surviving_node(monkeypatch):
    vectors = {"Redis Cache Cluster": _vec(0), "Redis": _vec(10)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))
    monkeypatch.setattr(
        "app.core.llm_provider.invoke_with_fallback",
        lambda *a, **k: json.dumps({"decisions": [{"index": 0, "same_system": True, "reason": "same cache system"}]}),
    )

    results = [
        _result(
            "MetadataExtractor",
            nodes=[_node("app_1", "Redis Cache Cluster", "Database"), _node("app_2", "Order Service")],
        ),
        _result(
            "LlmPromptExtractor",
            nodes=[_node("redis", "Redis")],
            edges=[DependencyEdge(source="redis", target="app_2", type="Sync", criticality="Medium", is_discovered=True)],
            confidence=0.55,
        ),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert {n.id for n in nodes} == {"app_1", "app_2"}
    assert len(edges) == 1
    assert edges[0].source == "app_1"  # remapped from the merged-away 'redis' id
    assert edges[0].target == "app_2"


def test_lexical_subset_pair_reaches_llm_despite_low_similarity(monkeypatch):
    """The real-world case that motivated adding the lexical-subset signal:
    Titan embeddings scored a bare shorthand ('Redis') at only ~0.52 cosine
    similarity against its full catalog name ('Redis Cache Cluster') in
    production - well below what intuition suggests for "obviously the same
    system". angle 80deg here (cos(80) ~= 0.17) is deliberately below
    settings.ENTITY_RESOLUTION_CANDIDATE_SIMILARITY_FLOOR (0.5 by default) to
    prove the token-subset check, not the similarity floor, is what makes
    this reach the LLM."""
    vectors = {"Redis Cache Cluster": _vec(0), "Redis": _vec(80)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))

    def _fake_invoke(system_prompt, user_prompt, agent_name, fallback_response):
        assert "Redis" in user_prompt
        return json.dumps({"decisions": [{"index": 0, "same_system": True, "reason": "shorthand reference"}]})

    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", _fake_invoke)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Redis Cache Cluster", "Database")]),
        _result("LlmPromptExtractor", nodes=[_node("redis", "Redis")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 1
    assert nodes[0].id == "app_1"


def test_unrelated_low_similarity_names_never_reach_llm(monkeypatch):
    """Sanity check for the lexical-subset signal's precision: two short,
    completely unrelated names with no shared significant tokens and low
    similarity must not become an LLM candidate."""
    vectors = {"Kafka": _vec(0), "Redis": _vec(90)}  # cos(90deg) = 0, no shared tokens either
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))

    def _boom(*args, **kwargs):
        raise AssertionError("no candidate pair should have been generated for these two names")

    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", _boom)

    results = [
        _result("MetadataExtractor", nodes=[_node("app_1", "Kafka", "Queue")]),
        _result("LlmPromptExtractor", nodes=[_node("redis", "Redis")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 2


def test_same_source_authoritative_nodes_never_merge_even_if_llm_says_same(monkeypatch):
    """Regression test for a real false-merge observed against the live
    corpus: two DIFFERENT rows in the same metadata catalog ("Returns
    Service" and "Returns-to-Vendor Service") are, by construction, already
    deliberately distinct entries in an authoritative source - an LLM
    judgment call must never override that, even if it says "same"."""
    vectors = {"Returns Service": _vec(0), "Returns-to-Vendor Service": _vec(35)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))

    def _boom(*args, **kwargs):
        raise AssertionError(
            "same-source authoritative pairs should be filtered out before ever reaching the LLM"
        )

    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", _boom)

    results = [
        _result(
            "MetadataExtractor",
            filename="System_Metadata_Catalog.xlsx",
            nodes=[
                _node("app_1092", "Returns-to-Vendor Service", "Microservice"),
                _node("app_1094", "Returns Service", "Microservice"),
            ],
        ),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert {n.id for n in nodes} == {"app_1092", "app_1094"}  # both survive, unmerged


def test_authoritative_nodes_from_different_sources_can_still_merge(monkeypatch):
    """The same-source guard must not overreach: two authoritative documents
    (even from the same extractor type) haven't already reconciled against
    EACH OTHER, so cross-document duplicates are still legitimate to merge."""
    vectors = {"Order Service": _vec(0), "OrderSvc": _vec(10)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))
    monkeypatch.setattr(
        "app.core.llm_provider.invoke_with_fallback",
        lambda *a, **k: json.dumps({"decisions": [{"index": 0, "same_system": True, "reason": "same service"}]}),
    )

    results = [
        _result("MetadataExtractor", filename="Catalog_A.xlsx", nodes=[_node("a1", "Order Service")]),
        _result("MetadataExtractor", filename="Catalog_B.xlsx", nodes=[_node("b1", "OrderSvc")]),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 1


def test_transitive_chain_never_combines_two_same_source_authoritative_nodes(monkeypatch):
    """The real bug this closes: a vague, low-priority mention ("Retail POS")
    got LLM-confirmed as the same system as BOTH "Retail POS Core" and a
    separately-catalogued country-specific deployment - two direct pairwise
    decisions that were never compared against each other, but which the
    union-find would otherwise chain into one node. Both catalog entries
    must survive; the vague mention may still merge into (at most) one."""
    vectors = {
        "Retail POS Core": _vec(0),
        "Retail POS - United States": _vec(2),
        "Retail POS": _vec(1),  # near both catalog entries
    }
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))
    monkeypatch.setattr(
        "app.core.llm_provider.invoke_with_fallback",
        lambda *a, **k: json.dumps(
            {
                "decisions": [
                    {"index": i, "same_system": True, "reason": "plausible match"}
                    for i in range(3)
                ]
            }
        ),
    )

    results = [
        _result(
            "MetadataExtractor",
            filename="System_Metadata_Catalog.xlsx",
            nodes=[
                _node("app_1110", "Retail POS Core", "Microservice"),
                _node("app_1174", "Retail POS - United States", "Microservice"),
            ],
        ),
        _result("LlmPromptExtractor", nodes=[_node("retail_pos", "Retail POS")], confidence=0.55),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    surviving_ids = {n.id for n in nodes}
    # The two catalog rows must never end up merged into a single node, even
    # transitively through the shared "Retail POS" mention.
    assert {"app_1110", "app_1174"} <= surviving_ids
    assert any("NOT merged" in w for w in warnings)


def test_large_candidate_list_is_split_into_multiple_reconciliation_calls(monkeypatch):
    """Regression test for a real failure observed against the live corpus:
    one LLM call for a large candidate list (one JSON decision object needed
    per pair) got cut off mid-response and silently reconciled nothing.
    _reconcile_all_candidates must split into batches small enough that no
    single call's response can be truncated, rather than trusting a bigger
    total cap alone."""
    call_sizes = []

    def _fake_invoke(system_prompt, user_prompt, agent_name, fallback_response):
        pair_count = user_prompt.count("] \"")
        call_sizes.append(pair_count)
        decisions = [{"index": i, "same_system": True, "reason": "test"} for i in range(pair_count)]
        return json.dumps({"decisions": decisions})

    monkeypatch.setattr("app.core.llm_provider.invoke_with_fallback", _fake_invoke)

    total = _RECONCILIATION_BATCH_SIZE * 2 + 3  # guarantees at least 3 batches
    candidates = [
        (_node(f"a{i}", f"Node A{i}"), _node(f"b{i}", f"Node B{i}"), 0.9) for i in range(total)
    ]

    decisions = _reconcile_all_candidates(candidates)

    assert len(decisions) == total
    assert all(decisions)  # every batch's "yes" decisions came through
    assert len(call_sizes) >= 3  # split into multiple calls, not one big one
    assert all(size <= _RECONCILIATION_BATCH_SIZE for size in call_sizes)
    assert sum(call_sizes) == total


def test_low_priority_extractor_never_survives_a_semantic_merge(monkeypatch):
    """The whole reason canonical_priority is threaded through the semantic
    merge: an LlmPromptExtractor node (priority 3, generic type placeholder)
    must never become the survivor over a MetadataExtractor node (priority 0,
    real attributes), regardless of which one embeds 'first'."""
    vectors = {"Order Service": _vec(0), "order svc (from prose)": _vec(5)}
    monkeypatch.setattr("app.core.embeddings.get_embedding_provider", lambda: _StubEmbeddingProvider(vectors))
    monkeypatch.setattr(
        "app.core.llm_provider.invoke_with_fallback",
        lambda *a, **k: json.dumps({"decisions": [{"index": 0, "same_system": True, "reason": "same service"}]}),
    )

    results = [
        # LLM result listed first/only priority-sorted-last regardless of list order.
        _result("LlmPromptExtractor", nodes=[_node("llm_order", "order svc (from prose)")], confidence=0.55),
        _result("MetadataExtractor", nodes=[_node("app_1", "Order Service", "Microservice")]),
    ]
    nodes, edges, warnings = merge_extraction_results(results)

    assert len(nodes) == 1
    assert nodes[0].id == "app_1"
