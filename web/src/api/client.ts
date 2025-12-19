/**
 * API client for MARO backend.
 */

import type { Graph, Channel, HistoryEvent } from '../types';

const API_BASE = import.meta.env.VITE_API_URL || '';

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`);
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
}

/**
 * Fetch requirements graph for a channel.
 */
export async function fetchGraph(channelId: string): Promise<Graph> {
  return fetchJson<Graph>(`/api/graphs/${channelId}`);
}

/**
 * Fetch graph metrics for a channel.
 */
export async function fetchMetrics(channelId: string): Promise<Graph['metrics']> {
  return fetchJson<Graph['metrics']>(`/api/graphs/${channelId}/metrics`);
}

/**
 * Validate a channel's graph.
 */
export async function validateGraph(
  channelId: string
): Promise<{ valid: boolean; issues: Record<string, unknown[]> }> {
  return fetchJson(`/api/graphs/${channelId}/validation`);
}

/**
 * Fetch change history for a channel.
 */
export async function fetchHistory(
  channelId: string,
  limit = 50
): Promise<{ events: HistoryEvent[]; total_events: number }> {
  return fetchJson(`/api/graphs/${channelId}/history?limit=${limit}`);
}

/**
 * Fetch all configured channels.
 */
export async function fetchChannels(): Promise<Channel[]> {
  return fetchJson<Channel[]>('/api/channels/');
}

/**
 * Update channel configuration.
 */
export async function updateChannel(
  channelId: string,
  config: Partial<Channel>
): Promise<Channel> {
  const response = await fetch(`${API_BASE}/api/channels/${channelId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
}
