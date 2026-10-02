import React, { useState } from 'react';
import { FileText, X, User, Bot } from 'lucide-react';
import type { CallRecord } from '../types';

interface HistoryTabProps {
  calls: CallRecord[];
  onRefresh: () => void;
}

export const HistoryTab: React.FC<HistoryTabProps> = ({ calls, onRefresh }) => {
  const [selectedCall, setSelectedCall] = useState<CallRecord | null>(null);
  const [sourceFilter, setSourceFilter] = useState<'all' | 'live' | 'simulated'>('all');

  const filteredCalls = calls.filter((c) => {
    if (sourceFilter === 'all') return true;
    return c.source === sourceFilter;
  });

  const getOutcomeBadge = (outcome?: string) => {
    switch (outcome) {
      case 'recovered':
        return <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800/40">Recovered</span>;
      case 'link_sent':
        return <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-sky-950 text-sky-300 border border-sky-800/40">Link Sent</span>;
      case 'scheduled':
        return <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-indigo-950 text-indigo-300 border border-indigo-800/40">Scheduled</span>;
      case 'escalate':
        return <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-950 text-amber-300 border border-amber-800/40">Escalated</span>;
      case 'verification_failed':
        return <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-950 text-rose-300 border border-rose-800/40">Auth Failed</span>;
      case 'declined':
      case 'wrong_party':
      default:
        return <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">{outcome || 'Pending'}</span>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Control bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            Historical Call Audit Records
            <span className="text-xs font-normal text-slate-400">({filteredCalls.length} records)</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Complete database audit log of live telephony sessions and synthetic persona simulator tests.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="bg-slate-950 p-1 rounded-lg border border-slate-800 flex items-center text-xs">
            <button
              onClick={() => setSourceFilter('all')}
              className={`px-3 py-1 rounded font-medium transition ${sourceFilter === 'all' ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-white'}`}
            >
              All
            </button>
            <button
              onClick={() => setSourceFilter('live')}
              className={`px-3 py-1 rounded font-medium transition ${sourceFilter === 'live' ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-white'}`}
            >
              Live Telephony
            </button>
            <button
              onClick={() => setSourceFilter('simulated')}
              className={`px-3 py-1 rounded font-medium transition ${sourceFilter === 'simulated' ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-white'}`}
            >
              Simulated
            </button>
          </div>

          <button
            onClick={onRefresh}
            className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-1.5 rounded-lg border border-slate-700 transition"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Calls Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/70 text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Call ID</th>
                <th className="py-3 px-4">Customer</th>
                <th className="py-3 px-4">Target Phone</th>
                <th className="py-3 px-4">Bank</th>
                <th className="py-3 px-4">Amount</th>
                <th className="py-3 px-4">Source</th>
                <th className="py-3 px-4">Outcome</th>
                <th className="py-3 px-4">Duration</th>
                <th className="py-3 px-4">Note</th>
                <th className="py-3 px-4 text-right">Transcript</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {filteredCalls.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-12 text-center text-slate-500">
                    No calls match the selected filter.
                  </td>
                </tr>
              ) : (
                filteredCalls.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-800/30 transition">
                    <td className="py-3 px-4 font-mono font-medium text-slate-300 truncate max-w-[140px]">{c.id}</td>
                    <td className="py-3 px-4 font-semibold text-white">
                      {c.customer_name || c.customer_id}
                      <span className="block text-[10px] text-slate-400 font-mono font-normal">{c.customer_id}</span>
                    </td>
                    <td className="py-3 px-4 font-mono text-slate-400">{c.phone_masked || '+91XXXXXX1234'}</td>
                    <td className="py-3 px-4 text-slate-300">{c.bank_name || 'N/A'}</td>
                    <td className="py-3 px-4 font-semibold text-emerald-400">
                      {c.amount_due ? `₹${c.amount_due.toLocaleString('en-IN')}` : '—'}
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-0.5 rounded font-mono text-[10px] uppercase font-semibold ${
                          c.source === 'simulated'
                            ? 'bg-purple-950 text-purple-300 border border-purple-800/40'
                            : 'bg-emerald-950 text-emerald-300 border border-emerald-800/40'
                        }`}
                      >
                        {c.source}
                      </span>
                    </td>
                    <td className="py-3 px-4">{getOutcomeBadge(c.outcome)}</td>
                    <td className="py-3 px-4 font-mono text-slate-400">{c.duration_sec}s</td>
                    <td className="py-3 px-4 text-slate-400 text-[11px] truncate max-w-[150px]">{c.note || '—'}</td>
                    <td className="py-3 px-4 text-right">
                      {c.transcript ? (
                        <button
                          onClick={() => setSelectedCall(c)}
                          className="inline-flex items-center gap-1 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs px-2.5 py-1 rounded font-medium border border-slate-700 transition"
                        >
                          <FileText className="w-3.5 h-3.5 text-sky-400" />
                          View
                        </button>
                      ) : (
                        <span className="text-slate-600 text-[11px]">No transcript</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Transcript Drawer Modal */}
      {selectedCall && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950">
              <div>
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  Call Transcript: {selectedCall.customer_name || selectedCall.customer_id}
                  <span className="text-[10px] font-mono uppercase bg-slate-800 text-sky-400 px-2 py-0.5 rounded">
                    {selectedCall.outcome}
                  </span>
                </h3>
                <p className="text-xs text-slate-400 font-mono mt-0.5">{selectedCall.id}</p>
              </div>

              <button
                onClick={() => setSelectedCall(null)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 overflow-y-auto space-y-3 bg-slate-950/40 text-xs font-sans">
              {(selectedCall.transcript || '').split('\n').filter(Boolean).map((line, idx) => {
                const isAgent = line.startsWith('agent:') || line.startsWith('assistant:');
                const cleanText = line.replace(/^(agent|assistant|customer|user):\s*/i, '');

                return (
                  <div
                    key={idx}
                    className={`flex items-start gap-2.5 ${isAgent ? 'justify-start' : 'justify-end'}`}
                  >
                    {isAgent && (
                      <div className="w-6 h-6 rounded-full bg-sky-600 text-white flex items-center justify-center shrink-0 mt-0.5">
                        <Bot className="w-3.5 h-3.5" />
                      </div>
                    )}
                    <div
                      className={`max-w-[85%] rounded-2xl px-4 py-2.5 leading-relaxed shadow-sm ${
                        isAgent
                          ? 'bg-slate-800 text-slate-200 rounded-tl-sm border border-slate-700/60'
                          : 'bg-sky-600 text-white rounded-tr-sm'
                      }`}
                    >
                      <div className="font-semibold text-[10px] uppercase tracking-wider mb-1 opacity-70">
                        {isAgent ? 'Aanya (AI Assistant)' : 'Customer'}
                      </div>
                      <div>{cleanText}</div>
                    </div>
                    {!isAgent && (
                      <div className="w-6 h-6 rounded-full bg-slate-700 text-slate-200 flex items-center justify-center shrink-0 mt-0.5">
                        <User className="w-3.5 h-3.5" />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="px-6 py-3 border-t border-slate-800 bg-slate-950 flex items-center justify-between text-xs text-slate-400">
              <span>Duration: <strong className="text-white font-mono">{selectedCall.duration_sec}s</strong></span>
              <button
                onClick={() => setSelectedCall(null)}
                className="bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-1.5 rounded-lg font-medium transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
