/**
 * Sidebar - Node details panel.
 */

import { X, ExternalLink } from 'lucide-react';
import type { GraphNode } from '../types';

interface SidebarProps {
  node: GraphNode;
  onClose: () => void;
}

export function Sidebar({ node, onClose }: SidebarProps) {
  return (
    <div className="w-80 bg-gray-800 border-l border-gray-700 flex flex-col">
      {/* Header */}
      <div className="h-14 px-4 flex items-center justify-between border-b border-gray-700">
        <h2 className="font-semibold text-white truncate">{String(node.title)}</h2>
        <button
          onClick={onClose}
          className="p-1 hover:bg-gray-700 rounded"
        >
          <X className="w-5 h-5 text-gray-400" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Type & Status */}
        <div className="flex gap-2">
          <span className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded uppercase">
            {String(node.type)}
          </span>
          <span
            className={`px-2 py-1 text-xs rounded ${
              node.status === 'synced'
                ? 'bg-blue-500/20 text-blue-400'
                : node.status === 'approved'
                ? 'bg-green-500/20 text-green-400'
                : node.status === 'conflict'
                ? 'bg-red-500/20 text-red-400'
                : 'bg-yellow-500/20 text-yellow-400'
            }`}
          >
            {String(node.status)}
          </span>
        </div>

        {/* Description */}
        {node.description && (
          <div>
            <h3 className="text-sm font-medium text-gray-400 mb-1">
              Description
            </h3>
            <p className="text-sm text-gray-300">{String(node.description)}</p>
          </div>
        )}

        {/* Acceptance Criteria */}
        {node.attributes?.acceptance_criteria && (
          <div>
            <h3 className="text-sm font-medium text-gray-400 mb-1">
              Acceptance Criteria
            </h3>
            <ul className="text-sm text-gray-300 space-y-1">
              {(node.attributes.acceptance_criteria as string[]).map(
                (ac, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-gray-500">-</span>
                    <span>{ac}</span>
                  </li>
                )
              )}
            </ul>
          </div>
        )}

        {/* Actor */}
        {node.attributes?.actor && (
          <div>
            <h3 className="text-sm font-medium text-gray-400 mb-1">Actor</h3>
            <p className="text-sm text-gray-300">
              {String(node.attributes.actor)}
            </p>
          </div>
        )}

        {/* Priority */}
        {node.attributes?.priority && (
          <div>
            <h3 className="text-sm font-medium text-gray-400 mb-1">Priority</h3>
            <span
              className={`px-2 py-1 text-xs rounded ${
                node.attributes?.priority === 'critical'
                  ? 'bg-red-500/20 text-red-400'
                  : node.attributes?.priority === 'high'
                  ? 'bg-orange-500/20 text-orange-400'
                  : 'bg-gray-700 text-gray-300'
              }`}
            >
              {String(node.attributes?.priority)}
            </span>
          </div>
        )}

        {/* External Reference */}
        {node.external_ref && (
          <div>
            <h3 className="text-sm font-medium text-gray-400 mb-1">
              External Link
            </h3>
            <a
              href={node.external_ref.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300"
            >
              <ExternalLink className="w-4 h-4" />
              {node.external_ref.system}: {node.external_ref.id}
            </a>
          </div>
        )}

        {/* Metadata */}
        <div className="pt-4 border-t border-gray-700">
          <h3 className="text-sm font-medium text-gray-400 mb-2">Metadata</h3>
          <div className="space-y-1 text-xs text-gray-500">
            <div>ID: {node.id}</div>
            <div>Created: {new Date(node.created_at).toLocaleString()}</div>
            <div>Updated: {new Date(node.updated_at).toLocaleString()}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
