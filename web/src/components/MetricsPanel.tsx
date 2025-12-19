/**
 * MetricsPanel - Overlay showing graph quality metrics.
 */

import { BarChart3, AlertTriangle, CheckCircle } from 'lucide-react';
import type { Metrics } from '../types';

interface MetricsPanelProps {
  metrics: Metrics;
}

export function MetricsPanel({ metrics }: MetricsPanelProps) {
  const completenessColor =
    metrics.completeness_score >= 80
      ? 'text-green-400'
      : metrics.completeness_score >= 50
      ? 'text-yellow-400'
      : 'text-red-400';

  return (
    <div className="bg-gray-800/90 backdrop-blur rounded-lg border border-gray-700 p-4 space-y-3 min-w-[200px]">
      <div className="flex items-center gap-2 text-gray-300">
        <BarChart3 className="w-4 h-4" />
        <span className="text-sm font-medium">Graph Metrics</span>
      </div>

      {/* Completeness */}
      <div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-400">Completeness</span>
          <span className={completenessColor}>
            {metrics.completeness_score.toFixed(1)}%
          </span>
        </div>
        <div className="mt-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${
              metrics.completeness_score >= 80
                ? 'bg-green-500'
                : metrics.completeness_score >= 50
                ? 'bg-yellow-500'
                : 'bg-red-500'
            }`}
            style={{ width: `${Math.min(metrics.completeness_score, 100)}%` }}
          />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="flex items-center gap-1">
          <CheckCircle className="w-3 h-3 text-blue-400" />
          <span className="text-gray-400">Nodes:</span>
          <span className="text-white">{metrics.total_nodes}</span>
        </div>
        <div className="flex items-center gap-1">
          <CheckCircle className="w-3 h-3 text-blue-400" />
          <span className="text-gray-400">Edges:</span>
          <span className="text-white">{metrics.total_edges}</span>
        </div>
      </div>

      {/* Warnings */}
      {(metrics.orphan_count > 0 ||
        metrics.conflict_ratio > 0 ||
        metrics.blocking_questions > 0) && (
        <div className="pt-2 border-t border-gray-700 space-y-1">
          {metrics.orphan_count > 0 && (
            <div className="flex items-center gap-2 text-sm text-yellow-400">
              <AlertTriangle className="w-3 h-3" />
              <span>{metrics.orphan_count} orphan nodes</span>
            </div>
          )}
          {metrics.conflict_ratio > 0 && (
            <div className="flex items-center gap-2 text-sm text-red-400">
              <AlertTriangle className="w-3 h-3" />
              <span>{metrics.conflict_ratio.toFixed(1)}% conflicts</span>
            </div>
          )}
          {metrics.blocking_questions > 0 && (
            <div className="flex items-center gap-2 text-sm text-orange-400">
              <AlertTriangle className="w-3 h-3" />
              <span>{metrics.blocking_questions} blocking questions</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
