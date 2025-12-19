/**
 * HistoryPanel - Shows graph change history.
 */

import { useEffect, useState } from 'react';
import { X, Clock, Plus, Edit, Trash2, Link } from 'lucide-react';
import { fetchHistory } from '../api/client';
import type { HistoryEvent } from '../types';

interface HistoryPanelProps {
  channelId: string | null;
  onClose: () => void;
}

const EVENT_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  node_created: Plus,
  node_updated: Edit,
  node_deleted: Trash2,
  edge_created: Link,
  edge_deleted: Trash2,
};

const EVENT_COLORS: Record<string, string> = {
  node_created: 'text-green-400',
  node_updated: 'text-blue-400',
  node_deleted: 'text-red-400',
  edge_created: 'text-purple-400',
  edge_deleted: 'text-red-400',
  sync_started: 'text-yellow-400',
  sync_completed: 'text-green-400',
  sync_failed: 'text-red-400',
};

export function HistoryPanel({ channelId, onClose }: HistoryPanelProps) {
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [totalEvents, setTotalEvents] = useState(0);

  useEffect(() => {
    if (!channelId) return;

    async function load() {
      try {
        setLoading(true);
        const data = await fetchHistory(channelId, 50);
        setEvents(data.events);
        setTotalEvents(data.total_events);
      } catch (e) {
        console.error('Failed to load history:', e);
      } finally {
        setLoading(false);
      }
    }

    load();
  }, [channelId]);

  return (
    <div className="w-80 bg-gray-800 border-l border-gray-700 flex flex-col">
      {/* Header */}
      <div className="h-14 px-4 flex items-center justify-between border-b border-gray-700">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-gray-400" />
          <h2 className="font-semibold text-white">History</h2>
          <span className="text-xs text-gray-500">({totalEvents})</span>
        </div>
        <button onClick={onClose} className="p-1 hover:bg-gray-700 rounded">
          <X className="w-5 h-5 text-gray-400" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 text-gray-400 text-sm">Loading...</div>
        ) : events.length === 0 ? (
          <div className="p-4 text-gray-400 text-sm">No events yet</div>
        ) : (
          <div className="divide-y divide-gray-700">
            {events.map((event) => {
              const Icon = EVENT_ICONS[event.type] || Clock;
              const colorClass = EVENT_COLORS[event.type] || 'text-gray-400';

              return (
                <div key={event.id} className="p-3 hover:bg-gray-700/50">
                  <div className="flex items-start gap-2">
                    <Icon className={`w-4 h-4 mt-0.5 ${colorClass}`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-gray-200">
                        {formatEventType(event.type)}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {formatPayload(event.payload)}
                      </div>
                      <div className="text-xs text-gray-600 mt-1">
                        {new Date(event.timestamp).toLocaleString()}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function formatEventType(type: string): string {
  return type
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatPayload(payload: Record<string, unknown>): string {
  if (payload.title) return payload.title as string;
  if (payload.node_id) return `Node: ${payload.node_id}`;
  if (payload.source_id && payload.target_id) {
    return `${payload.source_id} -> ${payload.target_id}`;
  }
  return '';
}
