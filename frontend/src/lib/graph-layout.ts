import dagre from "dagre";
import type { Edge, Node } from "@xyflow/react";

const NODE_WIDTH = 190;
const NODE_HEIGHT = 60;

/**
 * Hierarchical auto-layout (dagre) for React Flow graphs - replaces naive
 * fixed-radius circular placement, which overlaps once a topology has more
 * than a handful of nodes. Falls back to a simple grid when dagre can't
 * place a node (e.g. it has no edges at all).
 */
export function layoutWithDagre<T extends Node>(
  nodes: T[],
  edges: Pick<Edge, "source" | "target">[],
  direction: "LR" | "TB" = "LR",
): T[] {
  if (nodes.length === 0) return nodes;

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 50, ranksep: 110, marginx: 40, marginy: 40 });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    if (g.hasNode(edge.source) && g.hasNode(edge.target) && edge.source !== edge.target) {
      g.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(g);

  const columns = Math.ceil(Math.sqrt(nodes.length));
  return nodes.map((node, i) => {
    const pos = g.node(node.id);
    const fallback = { x: (i % columns) * (NODE_WIDTH + 40), y: Math.floor(i / columns) * (NODE_HEIGHT + 60) };
    return {
      ...node,
      position: pos && Number.isFinite(pos.x) ? { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 } : fallback,
      // Top-level width/height (not just style.width) - MiniMap draws each
      // node from these, not from the CSS style, and never renders a node at
      // all until it has *some* known dimensions. style.width alone (the only
      // thing set here previously) sizes the DOM element correctly but never
      // populates this, silently leaving the minimap blank.
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      style: { ...node.style, width: NODE_WIDTH },
    };
  });
}
