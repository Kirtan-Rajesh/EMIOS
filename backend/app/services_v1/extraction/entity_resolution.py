"""Cross-document entity resolution: merges the per-document ExtractionResults
from DocumentExtractionService into one deduplicated node/edge set.

Two tiers:

1. **Exact match** (`normalize_key`): a case/punctuation/abbreviation-insensitive
   identity key for a node name or id, e.g. a BRD's "the Payment Service", an
   ETL mapping's "PAYMENT_SVC", and a DB schema's "payment_service" table all
   resolve to one node. Free, deterministic, always on - never wrong, so it's
   the only tier allowed to merge nodes without asking anyone.
2. **LLM-adjudicated semantic match**: for nodes that don't share an exact key
   but might still be the same real system referred to differently (a BRD's
   shorthand "the cache layer" vs. a catalog's full "Redis Cache Cluster"; an
   inventory's "Finance" vs. a specific "Finance Consolidation & Close" app -
   which are almost certainly *different* things despite the shared word).
   Two cheap, deliberately generic heuristics - embedding-name cosine
   similarity, and whether one name's significant words are a subset of the
   other's - flag CANDIDATE pairs; every candidate is then decided by one
   batched LLM call, never by the heuristic score alone. This is intentional:
   name-embedding similarity for short entity names doesn't cleanly separate
   "same system, different phrasing" from "different systems that share a
   word" (empirically, against Amazon Titan Text Embeddings v2, "Redis" vs.
   "Redis Cache Cluster" scored *lower* similarity than "Retail POS Core" vs.
   a specific country's distinct POS deployment) - there is no safe numeric
   cutoff to auto-merge on. The heuristics only decide what's worth asking
   about; only an explicit, successfully-parsed LLM "yes" ever merges two
   nodes, and it defaults to "no" whenever it can't tell (a missed merge just
   leaves two nodes for a human to reconcile later; a wrong merge silently
   conflates two real systems in the digital twin).

Tier 2 needs a real embedding provider (and, for the reconciliation call, a
real LLM) to be worth anything - pass `enable_semantic_merge=False` to skip it
and get the old tier-1-only behavior, e.g. for a fixture/regression baseline
that must never make a paid API call (see
Northwind_Expected_Graph/generate_expected_graph.py). It also degrades
gracefully at runtime: if the embedding provider raises, tier 2 is skipped
with a warning rather than failing discovery; if no LLM is configured,
invoke_with_fallback() returns "no decisions", which this module correctly
treats as "leave every candidate pair unmerged" (the safe default), not as an
error.

Every merge and every dropped edge is recorded in the returned warnings list
so a human can audit exactly what got collapsed or discarded.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from app.agents import prompts
from app.core.config import settings
from app.services_v1.extraction.base import ExtractionResult
from app.models.schemas import DependencyEdge, ServiceNode

logger = logging.getLogger("emios")

_ABBREVIATIONS = {"db": "database", "svc": "service", "app": "application"}

# Lower number = more authoritative when two documents describe the same node.
# SchemaExtractor/MetadataExtractor/ApiSpecExtractor/StoredProcExtractor all know
# a system's real `type`/attributes; EtlMappingExtractor and LlmPromptExtractor
# often only reference a system in passing (to hang an edge off it) and fall
# back to a generic type="Microservice" placeholder - without this priority,
# whichever document happened to be uploaded most recently would win the merge
# (list_for_assessment orders newest-first), arbitrarily discarding the more
# informative node.
_EXTRACTOR_PRIORITY = {
    "SchemaExtractor": 0,
    "MetadataExtractor": 0,
    "ApiSpecExtractor": 0,
    "StoredProcExtractor": 1,
    "EtlMappingExtractor": 2,
    "LlmPromptExtractor": 3,
}

# Two independent, deliberately generic candidate-generation signals - neither
# one merges anything by itself, they only decide what's worth sending to the
# LLM (see module docstring for why a bare similarity cutoff can't safely
# auto-merge on its own):
#
# 1. Embedding-name cosine similarity at/above
#    settings.ENTITY_RESOLUTION_CANDIDATE_SIMILARITY_FLOOR (a recall knob, not
#    a decision boundary - see its definition in app/core/config.py for why).
# 2. One name's significant words being a subset of the other's (e.g. {"redis"}
#    subset-of {"redis", "cache", "cluster"}) - pure string logic, independent
#    of any embedding model's calibration, so it degrades gracefully across
#    embedding providers and domains the similarity floor doesn't generalize to.
_MIN_TOKEN_LENGTH_FOR_SUBSET_MATCH = 3
# Caps how many candidate pairs go into one reconciliation prompt/response, so
# the LLM's JSON response (one decision object per pair) can't itself run into
# the same token-truncation failure mode as the extraction prompt. If more
# candidates than this exist, lexical-subset matches are kept first (the
# provider-independent signal), then the most-similar remaining pairs fill any
# remaining room - the rest are left unmerged and noted in a warning rather
# than silently dropped.
_MAX_RECONCILIATION_PAIRS = 200
# Pairs per LLM reconciliation call - deliberately small: each decision needs
# its own JSON object (index + bool + short reason) in the response, so this
# is sized to comfortably fit under BEDROCK_MAX_TOKENS regardless of corpus
# size (see _reconcile_all_candidates, which batches instead of relying on
# _MAX_RECONCILIATION_PAIRS alone to bound a single call).
_RECONCILIATION_BATCH_SIZE = 15
_RECONCILIATION_MAX_WORKERS = 4
_EMBED_MAX_WORKERS = 8


def _name_tokens(name: str) -> Set[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    return {t for t in cleaned.split() if len(t) >= _MIN_TOKEN_LENGTH_FOR_SUBSET_MATCH}


def _is_lexical_subset_match(name_a: str, name_b: str) -> bool:
    """True if one name's significant words are entirely contained in the
    other's (either direction) - e.g. {"redis"} ⊆ {"redis", "cache",
    "cluster"}. Both token sets must be non-empty so two names with no
    significant words in common (or only short/stopword-like tokens) never
    match by default."""
    tokens_a, tokens_b = _name_tokens(name_a), _name_tokens(name_b)
    if not tokens_a or not tokens_b:
        return False
    return tokens_a <= tokens_b or tokens_b <= tokens_a


def normalize_key(value: str) -> str:
    """Case/punctuation/abbreviation-insensitive identity key for a node name or id."""
    cleaned = re.sub(r"[^a-z0-9_\s-]", "", value.lower())
    tokens = [t for t in re.split(r"[_\s-]+", cleaned) if t]
    tokens = [_ABBREVIATIONS.get(t, t) for t in tokens]
    merged = "".join(tokens)
    # Catch glued-together abbreviations a token split won't see (e.g. "PaymentDB").
    for abbr, full in _ABBREVIATIONS.items():
        if merged.endswith(abbr) and not merged.endswith(full):
            merged = merged[: -len(abbr)] + full
    return merged


def merge_extraction_results(
    results: List[ExtractionResult],
    enable_semantic_merge: bool = True,
) -> Tuple[List[ServiceNode], List[DependencyEdge], List[str]]:
    warnings: List[str] = []
    canonical_by_key: Dict[str, ServiceNode] = {}
    canonical_priority: Dict[str, int] = {}
    canonical_source: Dict[str, str] = {}
    id_to_canonical_id: Dict[str, str] = {}
    merged_raw_ids: Dict[str, Set[str]] = {}

    ordered_results = sorted(results, key=lambda r: _EXTRACTOR_PRIORITY.get(r.extractor, 99))

    for result in ordered_results:
        warnings.extend(f"[{result.source_filename}] {w}" for w in result.warnings)
        priority = _EXTRACTOR_PRIORITY.get(result.extractor, 99)

        for node in result.nodes:
            key = normalize_key(node.name or node.id)
            canonical = canonical_by_key.get(key)
            if canonical is None:
                canonical_by_key[key] = node
                canonical_priority[node.id] = priority
                canonical_source[node.id] = result.source_filename
                canonical = node
                merged_raw_ids[canonical.id] = {node.id}
            else:
                merged_raw_ids[canonical.id].add(node.id)
            id_to_canonical_id[node.id] = canonical.id

    for canonical_id, raw_ids in merged_raw_ids.items():
        if len(raw_ids) > 1:
            others = sorted(raw_ids - {canonical_id})
            warnings.append(
                f"Merged {len(raw_ids)} references into node '{canonical_id}' "
                f"(also seen as: {', '.join(others)})."
            )

    final_nodes = list(canonical_by_key.values())

    if enable_semantic_merge and len(final_nodes) > 1:
        final_nodes, id_to_canonical_id, semantic_warnings = _apply_semantic_merge(
            final_nodes, id_to_canonical_id, canonical_priority, canonical_source
        )
        warnings.extend(semantic_warnings)

    final_node_ids = {n.id for n in final_nodes}

    seen_edges: Set[Tuple[str, str]] = set()
    final_edges: List[DependencyEdge] = []
    # Same rationale as the node merge above: iterate in extractor-priority order
    # (not raw `results`, which is upload-recency order) so a deterministic
    # extractor's correctly-typed edge (e.g. EtlMappingExtractor's "DB"/"Async")
    # wins the (source, target) dedup below over a same-pair edge from a lower-
    # confidence extractor (LlmPromptExtractor always emits a generic "Sync"),
    # regardless of which document happened to be processed first.
    for result in ordered_results:
        for edge in result.edges:
            src = id_to_canonical_id.get(edge.source, edge.source)
            tgt = id_to_canonical_id.get(edge.target, edge.target)

            if src not in final_node_ids:
                warnings.append(
                    f"[{result.source_filename}] Dropped edge '{edge.source} -> {edge.target}': "
                    f"source '{src}' not found among extracted nodes."
                )
                continue
            if tgt not in final_node_ids:
                warnings.append(
                    f"[{result.source_filename}] Dropped edge '{edge.source} -> {edge.target}': "
                    f"target '{tgt}' not found among extracted nodes."
                )
                continue
            if src == tgt:
                warnings.append(
                    f"[{result.source_filename}] Dropped self-referential edge on '{src}' "
                    f"(source and target resolved to the same node)."
                )
                continue

            pair = (src, tgt)
            if pair in seen_edges:
                continue
            seen_edges.add(pair)
            final_edges.append(edge.model_copy(update={"source": src, "target": tgt}))

    return final_nodes, final_edges, warnings


def _embed_node_names(nodes: List[ServiceNode]) -> Dict[str, np.ndarray]:
    """Embeds each node's name (name only, not type/attributes - a mismatched
    type between an LLM's generic "Microservice" guess and a catalog's real
    "Database" would otherwise push two embeddings of the *same* system apart).
    Runs concurrently (embedding calls are independent I/O) since there can be
    a few hundred final nodes and each is a separate network call. A node
    whose embed() call fails is simply omitted - it just falls back to
    tier-1-only (exact match) behavior rather than aborting the whole batch."""
    from app.core.embeddings import get_embedding_provider

    try:
        provider = get_embedding_provider()
    except Exception as ex:
        logger.warning(f"No embedding provider available for entity resolution: {ex}")
        return {}

    embeddings: Dict[str, np.ndarray] = {}

    def _embed_one(node: ServiceNode) -> Tuple[str, Optional[np.ndarray]]:
        try:
            return node.id, np.array(provider.embed(node.name), dtype=np.float32)
        except Exception as ex:
            logger.warning(f"Could not embed node name '{node.name}' for entity resolution: {ex}")
            return node.id, None

    with ThreadPoolExecutor(max_workers=_EMBED_MAX_WORKERS) as pool:
        for node_id, vector in pool.map(_embed_one, nodes):
            if vector is not None:
                embeddings[node_id] = vector

    return embeddings


def _cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1e-12
    normalized = vectors / norms
    return normalized @ normalized.T


class _UnionFind:
    def __init__(self, ids: List[str]):
        self._parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for member in self._parent:
            out.setdefault(self.find(member), []).append(member)
        return out


def _reconcile_candidate_pairs(
    pairs: List[Tuple[ServiceNode, ServiceNode, float]],
) -> List[bool]:
    """One LLM call deciding same/different for each (node_a, node_b,
    similarity) candidate in `pairs` - callers are responsible for keeping
    `pairs` short enough that the response (one decision object per pair)
    can't be truncated before the JSON closes; see
    _RECONCILIATION_BATCH_SIZE/_reconcile_all_candidates below, which is what
    every real caller should use instead of this directly. Returns a
    same-length list of booleans, defaulting every entry to False (don't
    merge) if the LLM is unavailable, its response isn't valid JSON, or a
    given index is missing from its response - merging is only ever an
    explicit, successfully-parsed "yes"."""
    from app.core.llm_provider import invoke_with_fallback

    if not pairs:
        return []

    lines = [
        f'[{i}] "{a.name}" (type: {a.type}) vs "{b.name}" (type: {b.type})'
        for i, (a, b, _sim) in enumerate(pairs)
    ]
    usr_prompt = prompts.ENTITY_RECONCILIATION_USER_PROMPT.format(pairs_text="\n".join(lines))
    fallback = json.dumps({"decisions": []})

    raw_output = invoke_with_fallback(
        prompts.ENTITY_RECONCILIATION_SYSTEM_PROMPT, usr_prompt, "Entity Reconciliation Agent", fallback
    )

    decisions = [False] * len(pairs)
    try:
        parsed = json.loads(raw_output)
        for entry in parsed.get("decisions") or []:
            idx = entry.get("index")
            if isinstance(idx, int) and 0 <= idx < len(pairs) and entry.get("same_system") is True:
                decisions[idx] = True
    except (json.JSONDecodeError, TypeError, AttributeError) as ex:
        logger.warning(
            f"Entity reconciliation response for a batch of {len(pairs)} pair(s) was not valid JSON "
            f"(likely truncated - see _RECONCILIATION_BATCH_SIZE), none of this batch was merged: {ex}"
        )

    return decisions


def _reconcile_all_candidates(
    candidates: List[Tuple[ServiceNode, ServiceNode, float]],
) -> List[bool]:
    """Splits `candidates` into fixed-size batches and reconciles each with
    its own LLM call (run concurrently), rather than one call for
    however-many candidates a given run happens to produce. A single big
    call doesn't scale: each decision needs its own JSON object in the
    response (index + bool + a short reason), so a large-enough candidate
    list runs into the exact same output-token-truncation failure mode the
    extraction prompt did (see BEDROCK_MAX_TOKENS's history in
    app/core/config.py) - observed directly wiring this up: a single call for
    up to 60 pairs reliably got cut off mid-JSON and silently reconciled
    nothing. Fixed batch sizing avoids needing to predict/tune a "safe" total
    candidate count for every possible corpus."""
    if not candidates:
        return []

    batches = [
        candidates[i : i + _RECONCILIATION_BATCH_SIZE] for i in range(0, len(candidates), _RECONCILIATION_BATCH_SIZE)
    ]
    with ThreadPoolExecutor(max_workers=_RECONCILIATION_MAX_WORKERS) as pool:
        batch_decisions = list(pool.map(_reconcile_candidate_pairs, batches))

    decisions: List[bool] = []
    for batch_result in batch_decisions:
        decisions.extend(batch_result)
    return decisions


# Priority 0 = SchemaExtractor/MetadataExtractor/ApiSpecExtractor - parsers
# that read one structured, authoritative document (a catalog, an API spec)
# where each row/entry is already a deliberate enumeration of a distinct
# system, by construction. See _apply_semantic_merge's same-source guard.
_AUTHORITATIVE_PRIORITY = 0


def _apply_semantic_merge(
    final_nodes: List[ServiceNode],
    id_to_canonical_id: Dict[str, str],
    canonical_priority: Dict[str, int],
    canonical_source: Dict[str, str],
) -> Tuple[List[ServiceNode], Dict[str, str], List[str]]:
    warnings: List[str] = []

    embeddings = _embed_node_names(final_nodes)
    if len(embeddings) < 2:
        if final_nodes:
            warnings.append(
                "Semantic entity resolution skipped: no embedding provider produced usable vectors "
                "(falling back to exact-name matching only)."
            )
        return final_nodes, id_to_canonical_id, warnings

    embedded_nodes = [n for n in final_nodes if n.id in embeddings]
    matrix = np.stack([embeddings[n.id] for n in embedded_nodes])
    similarity = _cosine_similarity_matrix(matrix)
    similarity_floor = settings.ENTITY_RESOLUTION_CANDIDATE_SIMILARITY_FLOOR

    uf = _UnionFind([n.id for n in final_nodes])
    # Records *why* each merge happened, keyed by the pair that triggered it -
    # used only for the human-readable warning below, not for correctness
    # (union-find groups can merge transitively through several such pairs).
    union_reasons: Dict[Tuple[str, str], str] = {}

    # Guards against the direct-pair source check above being defeated
    # transitively: e.g. a vague LLM-sourced "Retail POS" mention getting
    # confirmed as the same system as *both* "Retail POS Core" AND a specific
    # country's separately-catalogued POS deployment would otherwise chain
    # those two catalog rows into one node despite them never being directly
    # compared. Tracks, per current group root, which authoritative
    # (source_filename, priority-0) entries that group already contains -
    # a union that would put a second entry from the *same* source into one
    # group is refused, no matter how many hops away the trigger pair is.
    group_authoritative_sources: Dict[str, Set[str]] = {
        node.id: ({canonical_source[node.id]} if canonical_priority.get(node.id) == _AUTHORITATIVE_PRIORITY else set())
        for node in final_nodes
    }

    def _try_union(id_a: str, id_b: str) -> bool:
        root_a, root_b = uf.find(id_a), uf.find(id_b)
        if root_a == root_b:
            return True
        sources_a = group_authoritative_sources.get(root_a, set())
        sources_b = group_authoritative_sources.get(root_b, set())
        if sources_a & sources_b:
            return False
        uf.union(root_a, root_b)
        group_authoritative_sources[uf.find(root_a)] = sources_a | sources_b
        return True
    # (node_a, node_b, similarity, is_lexical_subset_match) - every entry here
    # is a *candidate* for the LLM to judge, never merged on the heuristic alone.
    candidates: List[Tuple[ServiceNode, ServiceNode, float, bool]] = []

    for i in range(len(embedded_nodes)):
        for j in range(i + 1, len(embedded_nodes)):
            id_a, id_b = embedded_nodes[i].id, embedded_nodes[j].id
            # Never second-guess a single authoritative document's own
            # row-level distinctions: if both nodes came from the SAME
            # structured/authoritative source (e.g. two different rows in one
            # metadata catalog), that source already deliberately kept them
            # separate - an embedding heuristic plus a small LLM's guess
            # shouldn't override the source of truth it was itself parsed
            # from. Two authoritative documents (even the same extractor
            # type) are still fair game - only *within* one document is this
            # guarantee real.
            if (
                canonical_priority.get(id_a) == _AUTHORITATIVE_PRIORITY
                and canonical_priority.get(id_b) == _AUTHORITATIVE_PRIORITY
                and canonical_source.get(id_a) == canonical_source.get(id_b)
            ):
                continue
            sim = float(similarity[i, j])
            is_lexical = _is_lexical_subset_match(embedded_nodes[i].name, embedded_nodes[j].name)
            if sim >= similarity_floor or is_lexical:
                candidates.append((embedded_nodes[i], embedded_nodes[j], sim, is_lexical))

    if candidates:
        # Lexical-subset matches first (a provider-independent signal, so kept
        # even if the cap would otherwise crowd them out with high-similarity-
        # but-not-lexically-related pairs), then by descending similarity.
        candidates.sort(key=lambda c: (not c[3], -c[2]))
        if len(candidates) > _MAX_RECONCILIATION_PAIRS:
            warnings.append(
                f"Entity reconciliation found {len(candidates)} candidate pair(s); only the "
                f"{_MAX_RECONCILIATION_PAIRS} most promising were sent to the LLM for a decision, the "
                f"rest were left unmerged."
            )
            candidates = candidates[:_MAX_RECONCILIATION_PAIRS]

        pairs_for_llm = [(a, b, sim) for a, b, sim, _is_lexical in candidates]
        decisions = _reconcile_all_candidates(pairs_for_llm)
        for (node_a, node_b, sim), same in zip(pairs_for_llm, decisions):
            if not same:
                continue
            if _try_union(node_a.id, node_b.id):
                union_reasons[(node_a.id, node_b.id)] = f"LLM-confirmed, similarity {sim:.2f}"
            else:
                warnings.append(
                    f"[Semantic merge] LLM confirmed '{node_a.name}' ({node_a.id}) and '{node_b.name}' "
                    f"({node_b.id}) as the same system, but NOT merged: doing so would have transitively "
                    f"combined two separately-catalogued entries from the same authoritative source - "
                    f"kept as distinct nodes for a human to review."
                )

    node_by_id = {n.id: n for n in final_nodes}
    order = {n.id: idx for idx, n in enumerate(final_nodes)}
    remap: Dict[str, str] = {}
    survivors: List[ServiceNode] = []

    for group in uf.groups().values():
        if len(group) == 1:
            survivors.append(node_by_id[group[0]])
            continue
        # Most-authoritative extractor wins; ties broken by original position
        # in `final_nodes` (deterministic, not dependent on dict/set ordering).
        survivor_id = min(group, key=lambda nid: (canonical_priority.get(nid, 99), order[nid]))
        survivors.append(node_by_id[survivor_id])
        for member_id in group:
            if member_id == survivor_id:
                continue
            remap[member_id] = survivor_id
            reason = union_reasons.get((member_id, survivor_id)) or union_reasons.get((survivor_id, member_id))
            detail = f" ({reason})" if reason else " (merged via a transitive semantic match)"
            warnings.append(
                f"[Semantic merge] Merged '{node_by_id[member_id].name}' ({member_id}) into "
                f"'{node_by_id[survivor_id].name}' ({survivor_id}){detail}."
            )

    new_id_to_canonical_id = {
        raw_id: remap.get(tier1_id, tier1_id) for raw_id, tier1_id in id_to_canonical_id.items()
    }
    return survivors, new_id_to_canonical_id, warnings
