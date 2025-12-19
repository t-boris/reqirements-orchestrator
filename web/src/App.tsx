import { useState, useEffect } from 'react';
import { GraphView } from './components/GraphView';
import { Sidebar } from './components/Sidebar';
import { MetricsPanel } from './components/MetricsPanel';
import { ChannelNav } from './components/ChannelNav';
import { HistoryPanel } from './components/HistoryPanel';
import { fetchGraph, fetchChannels } from './api/client';
import type { Graph, Channel, GraphNode } from './types';

const POLLING_INTERVAL = 5000; // 5 seconds

function App() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load channels on mount
  useEffect(() => {
    loadChannels();
  }, []);

  // Poll for graph updates
  useEffect(() => {
    if (!selectedChannel) return;

    loadGraph(selectedChannel);

    const interval = setInterval(() => {
      loadGraph(selectedChannel);
    }, POLLING_INTERVAL);

    return () => clearInterval(interval);
  }, [selectedChannel]);

  async function loadChannels() {
    try {
      const data = await fetchChannels();
      setChannels(data);
      if (data.length > 0 && !selectedChannel) {
        setSelectedChannel(data[0].channel_id);
      }
    } catch (e) {
      setError('Failed to load channels');
    }
  }

  async function loadGraph(channelId: string) {
    try {
      setLoading(true);
      const data = await fetchGraph(channelId);
      setGraph(data);
      setError(null);
    } catch (e) {
      setError('Failed to load graph');
    } finally {
      setLoading(false);
    }
  }

  function handleNodeClick(node: GraphNode) {
    setSelectedNode(node);
  }

  return (
    <div className="flex h-screen bg-gray-900">
      {/* Left: Channel Navigation */}
      <ChannelNav
        channels={channels}
        selectedChannel={selectedChannel}
        onSelectChannel={setSelectedChannel}
      />

      {/* Center: Graph Visualization */}
      <div className="flex-1 flex flex-col">
        {/* Top bar */}
        <header className="h-14 bg-gray-800 border-b border-gray-700 flex items-center justify-between px-4">
          <h1 className="text-lg font-semibold text-white">
            MARO Requirements Graph
          </h1>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setShowHistory(!showHistory)}
              className={`px-3 py-1.5 rounded text-sm ${
                showHistory
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              History
            </button>
          </div>
        </header>

        {/* Graph view */}
        <div className="flex-1 relative">
          {loading && !graph && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-900">
              <div className="text-gray-400">Loading graph...</div>
            </div>
          )}

          {error && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-900">
              <div className="text-red-400">{error}</div>
            </div>
          )}

          {graph && (
            <GraphView
              nodes={graph.nodes}
              edges={graph.edges}
              onNodeClick={handleNodeClick}
            />
          )}

          {/* Metrics overlay */}
          {graph && (
            <div className="absolute top-4 left-4">
              <MetricsPanel metrics={graph.metrics} />
            </div>
          )}
        </div>
      </div>

      {/* Right: Sidebar (node details or history) */}
      {showHistory ? (
        <HistoryPanel
          channelId={selectedChannel}
          onClose={() => setShowHistory(false)}
        />
      ) : (
        selectedNode && (
          <Sidebar node={selectedNode} onClose={() => setSelectedNode(null)} />
        )
      )}
    </div>
  );
}

export default App;
