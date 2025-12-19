/**
 * RequirementNode - Custom React Flow node for requirements.
 */

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { clsx } from 'clsx';
import {
  Target,
  Layers,
  FileText,
  CheckSquare,
  Box,
  Shield,
  AlertTriangle,
  HelpCircle,
  FileQuestion,
} from 'lucide-react';
import type { NodeType } from '../types';

// Icon mapping for node types
const TYPE_ICONS: Record<NodeType, React.ComponentType<{ className?: string; style?: React.CSSProperties }>> = {
  goal: Target,
  epic: Layers,
  story: FileText,
  subtask: CheckSquare,
  component: Box,
  constraint: Shield,
  risk: AlertTriangle,
  question: HelpCircle,
  context: FileQuestion,
};

interface NodeData {
  id: string;
  type: NodeType;
  title: string;
  status: string;
  color: string;
}

interface RequirementNodeProps {
  data: NodeData;
}

export const RequirementNode = memo(({ data }: RequirementNodeProps) => {
  const Icon = TYPE_ICONS[data.type] || FileText;

  return (
    <div
      className={clsx(
        'px-4 py-3 rounded-lg border-2 bg-gray-800 shadow-lg min-w-[180px] max-w-[220px]',
        'hover:shadow-xl transition-shadow cursor-pointer'
      )}
      style={{ borderColor: data.color }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-gray-600 !w-3 !h-3"
      />

      <div className="flex items-start gap-2">
        <div
          className="p-1.5 rounded"
          style={{ backgroundColor: `${data.color}20` }}
        >
          <Icon className="w-4 h-4" style={{ color: data.color }} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-xs text-gray-400 uppercase tracking-wide">
            {data.type}
          </div>
          <div className="text-sm font-medium text-gray-100 truncate">
            {data.title}
          </div>
        </div>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span
          className="text-xs px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: `${data.color}20`,
            color: data.color,
          }}
        >
          {data.status}
        </span>
        <span className="text-xs text-gray-500">#{data.id}</span>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-gray-600 !w-3 !h-3"
      />
    </div>
  );
});

RequirementNode.displayName = 'RequirementNode';
