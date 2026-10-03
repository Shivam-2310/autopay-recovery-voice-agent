import React from 'react';
import { Phone, Radio, AlertTriangle, MessageSquare, History, LayoutDashboard } from 'lucide-react';
import type { SystemConfig } from '../types';
import type { WebSocketStatus } from '../hooks/useWebSocket';

interface HeaderProps {
  config: SystemConfig | null;
  wsStatus: WebSocketStatus;
  activeTab: 'overview' | 'live' | 'messages' | 'history';
  setActiveTab: (tab: 'overview' | 'live' | 'messages' | 'history') => void;
  hasActiveCall: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  config,
  wsStatus,
  activeTab,
  setActiveTab,
  hasActiveCall,
}) => {
  const getStatusColor = () => {
    switch (wsStatus) {
      case 'connected': return 'bg-emerald-500';
      case 'connecting': return 'bg-amber-500 animate-pulse';
      case 'error':
      case 'disconnected':
      default: return 'bg-rose-500';
    }
  };

  return (
    <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-40">
      {/* Top Demo Banner */}
      <div className="bg-slate-950 px-4 py-1.5 border-b border-slate-800/60 text-xs flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 font-semibold text-amber-400 bg-amber-950/60 px-2 py-0.5 rounded border border-amber-800/40">
            <AlertTriangle className="w-3.5 h-3.5" />
            TELEPHONY TEST ROUTING
          </span>
          <span className="text-slate-400">
            Active Call & SMS target:{' '}
            <strong className="text-sky-300 font-mono font-bold">
              {config?.demo_phone || config?.demo_phone_masked || '+91XXXXXXXXXX'}
            </strong>
          </span>
        </div>

        <div className="flex items-center gap-3">
          {config?.demo_override ? (
            <span className="bg-purple-950/80 text-purple-300 border border-purple-800/50 px-2 py-0.5 rounded font-mono text-[11px]">
              ⚡ DEMO_OVERRIDE=true (Window & Daily Limits Bypassed)
            </span>
          ) : (
            <span className={`px-2 py-0.5 rounded font-mono text-[11px] ${config?.in_call_window ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/50' : 'bg-amber-950/80 text-amber-300 border border-amber-800/50'}`}>
              IST Call Window: {config?.call_window_status || 'Checking...'}
            </span>
          )}

          <span className="bg-slate-800 text-slate-300 px-2 py-0.5 rounded font-mono text-[11px]">
            SMS: <strong className="text-sky-400 uppercase">{config?.sms_mode || 'mock'}</strong>
          </span>

          <div className="flex items-center gap-1.5 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
            <span className={`w-2 h-2 rounded-full ${getStatusColor()}`} />
            <span className="text-slate-400 text-[11px] capitalize">{wsStatus}</span>
          </div>
        </div>
      </div>

      {/* Main Navigation Bar */}
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-sky-600 flex items-center justify-center shadow-lg shadow-sky-600/20">
            <Phone className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
              PayEase Autopay Recovery
              <span className="text-[10px] uppercase tracking-wider font-semibold bg-sky-950 text-sky-400 px-2 py-0.5 rounded border border-sky-800/50">
                Voice Agent
              </span>
            </h1>
            <p className="text-xs text-slate-400">Deterministic Guardrails & Real-Time SIP Telemetry</p>
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800">
          <button
            onClick={() => setActiveTab('overview')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'overview'
                ? 'bg-sky-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <LayoutDashboard className="w-3.5 h-3.5" />
            Overview
          </button>

          <button
            onClick={() => setActiveTab('live')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all relative ${
              activeTab === 'live'
                ? 'bg-sky-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <Radio className="w-3.5 h-3.5" />
            Live Call
            {hasActiveCall && (
              <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-rose-500 rounded-full animate-ping" />
            )}
            {hasActiveCall && (
              <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-rose-500 rounded-full" />
            )}
          </button>

          <button
            onClick={() => setActiveTab('messages')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'messages'
                ? 'bg-sky-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            SMS & Links
          </button>

          <button
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'history'
                ? 'bg-sky-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <History className="w-3.5 h-3.5" />
            Call History
          </button>
        </nav>
      </div>
    </header>
  );
};
