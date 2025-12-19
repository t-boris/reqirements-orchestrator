/**
 * ChannelNav - Left sidebar for channel navigation.
 */

import { Hash, Settings } from 'lucide-react';
import type { Channel } from '../types';

interface ChannelNavProps {
  channels: Channel[];
  selectedChannel: string | null;
  onSelectChannel: (channelId: string) => void;
}

export function ChannelNav({
  channels,
  selectedChannel,
  onSelectChannel,
}: ChannelNavProps) {
  return (
    <div className="w-60 bg-gray-800 border-r border-gray-700 flex flex-col">
      {/* Header */}
      <div className="h-14 px-4 flex items-center border-b border-gray-700">
        <h1 className="text-lg font-bold text-white">MARO</h1>
      </div>

      {/* Channel list */}
      <div className="flex-1 overflow-y-auto py-2">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Channels
          </h2>
        </div>

        {channels.length === 0 ? (
          <div className="px-3 py-4 text-sm text-gray-500">
            No channels configured
          </div>
        ) : (
          <nav className="space-y-0.5 px-2">
            {channels.map((channel) => (
              <button
                key={channel.channel_id}
                onClick={() => onSelectChannel(channel.channel_id)}
                className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-sm ${
                  selectedChannel === channel.channel_id
                    ? 'bg-gray-700 text-white'
                    : 'text-gray-400 hover:bg-gray-700/50 hover:text-gray-200'
                }`}
              >
                <Hash className="w-4 h-4" />
                <span className="truncate">
                  {channel.channel_id.slice(0, 12)}
                </span>
                {channel.jira_project_key && (
                  <span className="ml-auto text-xs text-gray-500">
                    {channel.jira_project_key}
                  </span>
                )}
              </button>
            ))}
          </nav>
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-gray-700">
        <button className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-sm text-gray-400 hover:bg-gray-700/50 hover:text-gray-200">
          <Settings className="w-4 h-4" />
          <span>Settings</span>
        </button>
      </div>
    </div>
  );
}
