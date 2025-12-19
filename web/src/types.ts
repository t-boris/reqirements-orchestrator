/**
 * TypeScript types for the MARO dashboard.
 */

export type NodeType =
  | 'goal'
  | 'epic'
  | 'story'
  | 'subtask'
  | 'component'
  | 'constraint'
  | 'risk'
  | 'question'
  | 'context';

export type NodeStatus =
  | 'draft'
  | 'approved'
  | 'synced'
  | 'partially_synced'
  | 'conflict';

export type EdgeType =
  | 'decomposes_to'
  | 'depends_on'
  | 'requires_component'
  | 'constrained_by'
  | 'conflicts_with'
  | 'mitigates'
  | 'blocks';

export interface ExternalRef {
  system: string;
  id: string;
  url: string;
}

export interface GraphNode {
  id: string;
  type: NodeType;
  title: string;
  description: string;
  status: NodeStatus;
  attributes: Record<string, unknown>;
  external_ref: ExternalRef | null;
  created_at: string;
  updated_at: string;
}

export interface GraphEdge {
  source_id: string;
  target_id: string;
  type: EdgeType;
  attributes: Record<string, unknown>;
}

export interface Metrics {
  completeness_score: number;
  conflict_ratio: number;
  orphan_count: number;
  unlinked_stories: number;
  blocking_questions: number;
  total_nodes: number;
  total_edges: number;
}

export interface Graph {
  channel_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  metrics: Metrics;
  updated_at: string;
}

export interface Channel {
  channel_id: string;
  jira_project_key: string;
  jira_project_id: string;
  enabled: boolean;
}

export interface HistoryEvent {
  id: string;
  type: string;
  user_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}
