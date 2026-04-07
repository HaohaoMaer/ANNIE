"use client";

import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { NPC_COLORS } from "@/lib/constants";
import type { SocialGraphData, GraphEdge } from "@/lib/types";

interface SocialGraphVizProps {
  graphData: SocialGraphData;
  highlightNpc?: string | null;
  compact?: boolean;
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  trust: number;
  emotional_valence: number;
  type: string;
  status: string;
}

function valenceColor(v: number): string {
  if (v >= 0.3) return "#10b981";
  if (v <= -0.3) return "#ef4444";
  return "#64748b";
}

export function SocialGraphViz({ graphData, highlightNpc, compact }: SocialGraphVizProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<d3.Simulation<SimNode, SimLink>>(null);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const width = rect.width || 360;
    const height = rect.height || 300;

    svg.selectAll("*").remove();

    if (graphData.nodes.length === 0) return;

    const nodes: SimNode[] = graphData.nodes.map((n) => ({ ...n }));
    const links: SimLink[] = graphData.edges.map((e) => ({
      source: e.source,
      target: e.target,
      trust: e.trust,
      emotional_valence: e.emotional_valence,
      type: e.type,
      status: e.status,
    }));

    const g = svg.append("g");

    // Zoom
    (svg as unknown as d3.Selection<SVGSVGElement, unknown, null, undefined>).call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.5, 3])
        .on("zoom", (event) => g.attr("transform", event.transform))
    );

    // Links
    const link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (d) => valenceColor(d.emotional_valence))
      .attr("stroke-width", (d) => Math.max(1, d.trust * 4))
      .attr("stroke-opacity", 0.6)
      .attr("stroke-dasharray", (d) => (d.status === "broken" ? "6 4" : null));

    // Node groups
    const node = g
      .append("g")
      .selectAll<SVGGElement, SimNode>("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "pointer");

    // Node circles
    node
      .append("circle")
      .attr("r", compact ? 16 : 22)
      .attr("fill", "#0f172a")
      .attr("stroke", (d) => NPC_COLORS[d.id] ?? "#64748b")
      .attr("stroke-width", (d) => (highlightNpc === d.id ? 4 : 2.5))
      .attr("opacity", (d) =>
        highlightNpc && highlightNpc !== d.id ? 0.4 : 1
      );

    // Node labels
    node
      .append("text")
      .text((d) => d.label.charAt(0))
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", (d) => NPC_COLORS[d.id] ?? "#94a3b8")
      .attr("font-size", compact ? 10 : 13)
      .attr("font-weight", "bold")
      .attr("pointer-events", "none");

    // Simulation
    const sim = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3.forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(compact ? 60 : 100).strength((d) => d.trust * 0.5 + 0.1)
      )
      .force("charge", d3.forceManyBody().strength(compact ? -150 : -250))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide(compact ? 22 : 30));

    sim.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as SimNode).x!)
        .attr("y1", (d) => (d.source as SimNode).y!)
        .attr("x2", (d) => (d.target as SimNode).x!)
        .attr("y2", (d) => (d.target as SimNode).y!);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    simRef.current = sim;

    // Drag
    node.call(
      d3.drag<SVGGElement, SimNode>()
        .on("start", (event, d) => {
          if (!event.active) sim.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        })
    );

    return () => {
      sim.stop();
    };
  }, [graphData, highlightNpc, compact]);

  return (
    <svg
      ref={svgRef}
      className="h-full w-full"
      style={{ minHeight: compact ? 150 : 280 }}
    />
  );
}
