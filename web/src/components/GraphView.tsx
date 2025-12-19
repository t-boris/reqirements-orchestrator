/**
 * GraphView - React Flow based graph visualization.
 */

import { useCallback, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  NodeTypes,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { RequirementNode } from './RequirementNode';
import type { GraphNode, GraphEdge, NodeStatus } from '../types';

interface GraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick: (node: GraphNode) => void;
}

// Status to color mapping
const STATUS_COLORS: Record<NodeStatus, string> = {
  draft: '#fbbf24',
  approved: '#22c55e',
  synced: '#3b82f6',
  partially_synced: '#f97316',
  conflict: '#ef4444',
};

// Custom node types
const nodeTypes: NodeTypes = {
  requirement: RequirementNode as NodeTypes['requirement'],
};

// Layout constants
const NODE_WIDTH = 200;
const LAYER_SPACING = 150;
const NODE_SPACING = 50;

// Type order for layering
const TYPE_LAYERS: Record<string, number> = {
  goal: 0,
  epic: 1,
  story: 2,
  subtask: 3,
  component: 2,
  constraint: 3,
  risk: 3,
  question: 4,
  context: 4,
};

export function GraphView({ nodes, edges, onNodeClick }: GraphViewProps) {
  // Convert to React Flow format
  const flowNodes = useMemo(() => {
    // Group nodes by layer
    const layers: Map<number, GraphNode[]> = new Map();

    nodes.forEach((node) => {
      const layer = TYPE_LAYERS[node.type] ?? 2;
      if (!layers.has(layer)) {
        layers.set(layer, []);
      }
      layers.get(layer)!.push(node);
    });

    // Position nodes
    const result: Node[] = [];

    layers.forEach((layerNodes, layer) => {
      const y = layer * LAYER_SPACING;
      const startX = -(layerNodes.length * (NODE_WIDTH + NODE_SPACING)) / 2;

      layerNodes.forEach((node, index) => {
        result.push({
          id: node.id,
          type: 'requirement',
          position: {
            x: startX + index * (NODE_WIDTH + NODE_SPACING),
            y,
          },
          data: {
            ...node,
            color: STATUS_COLORS[node.status],
          },
        });
      });
    });

    return result;
  }, [nodes]);

  const flowEdges = useMemo(() => {
    return edges.map((edge): Edge => ({
      id: `${edge.source_id}-${edge.target_id}`,
      source: edge.source_id,
      target: edge.target_id,
      label: edge.type.replace(/_/g, ' '),
      style: {
        stroke: edge.type === 'conflicts_with' ? '#ef4444' : '#6b7280',
      },
      animated: edge.type === 'blocks',
    }));
  }, [edges]);

  const [reactFlowNodes, , onNodesChange] = useNodesState(flowNodes);
  const [reactFlowEdges, , onEdgesChange] = useEdgesState(flowEdges);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const graphNode = nodes.find((n) => n.id === node.id);
      if (graphNode) {
        onNodeClick(graphNode);
      }
    },
    [nodes, onNodeClick]
  );

  return (
    <ReactFlow
      nodes={reactFlowNodes}
      edges={reactFlowEdges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={handleNodeClick}
      nodeTypes={nodeTypes}
      fitView
      minZoom={0.1}
      maxZoom={2}
      className="bg-gray-900"
    >
      <Background color="#374151" gap={20} />
      <Controls />
      <MiniMap
        nodeColor={(node) => (node.data?.color as string) || '#6b7280'}
        maskColor="rgba(0, 0, 0, 0.8)"
      />
    </ReactFlow>
  );
}
