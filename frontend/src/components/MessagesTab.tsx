import React from 'react';
import { MessageSquare, ExternalLink, CheckCircle2, AlertTriangle } from 'lucide-react';
import type { MessageEvent, LinkEvent } from '../types';

interface MessagesTabProps {
  messages: MessageEvent[];
  linkEvents: LinkEvent[];
  smsMode: string;
}

export const MessagesTab: React.FC<MessagesTabProps> = ({
  messages,
  linkEvents,
  smsMode,
}) => {
  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            SMS Payment Links & Funnel Telemetry
            <span className="text-[10px] font-mono uppercase bg-slate-800 text-sky-400 px-2 py-0.5 rounded border border-slate-700">
              Mode: {smsMode}
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Full conversion tracking from SMS dispatch to mock Razorpay portal completion.
          </p>
        </div>

        <div className="text-xs text-slate-400 bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800">
          Link Funnel: <span className="text-sky-400 font-mono">created → sent → delivered → clicked → paid</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── SMS Messages Feed ── */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
          <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between bg-slate-950/70">
            <h3 className="text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-sky-400" />
              SMS Dispatches ({messages.length})
            </h3>
            <span className="text-xs text-slate-400 font-mono">Twilio API Logs</span>
          </div>

          <div className="p-4 space-y-3">
            {messages.length === 0 ? (
              <div className="text-center py-10 text-slate-500 text-xs">
                No SMS payment links dispatched yet.
              </div>
            ) : (
              messages.map((m, idx) => (
                <div
                  key={m.sid || idx}
                  className="bg-slate-950 border border-slate-800/80 rounded-lg p-3.5 text-xs space-y-2 hover:border-slate-700 transition"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sky-400 font-semibold">{m.sid}</span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium ${
                        m.status === 'delivered'
                          ? 'bg-emerald-950 text-emerald-300 border border-emerald-800/40'
                          : m.status === 'failed'
                          ? 'bg-rose-950 text-rose-300 border border-rose-800/40'
                          : 'bg-sky-950 text-sky-300 border border-sky-800/40'
                      }`}
                    >
                      {m.status.toUpperCase()}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-slate-400 text-[11px]">
                    <div>To: <strong className="text-slate-200">{m.to_masked || '+91XXXXXX1234'}</strong></div>
                    <div>Call ID: <span className="font-mono text-slate-300">{m.call_id}</span></div>
                    {m.error_code && (
                      <div className="col-span-2 text-rose-400 flex items-center gap-1 font-mono">
                        <AlertTriangle className="w-3.5 h-3.5" /> Error Code: {m.error_code}
                      </div>
                    )}
                  </div>

                  {m.url && (
                    <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between">
                      <span className="text-[11px] font-mono text-slate-400 truncate max-w-[260px]">{m.url}</span>
                      <a
                        href={m.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-sky-400 hover:text-sky-300 bg-sky-950 px-2 py-1 rounded border border-sky-800/40 transition"
                      >
                        Open Portal
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* ── Link Events Funnel ── */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
          <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between bg-slate-950/70">
            <h3 className="text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              Link Funnel Events ({linkEvents.length})
            </h3>
            <span className="text-xs text-slate-400 font-mono">Real-Time</span>
          </div>

          <div className="p-4 space-y-2.5">
            {linkEvents.length === 0 ? (
              <div className="text-center py-10 text-slate-500 text-xs">
                No link activity registered yet.
              </div>
            ) : (
              linkEvents.map((le, idx) => (
                <div
                  key={idx}
                  className="bg-slate-950 border border-slate-800/80 rounded-lg px-3.5 py-2.5 text-xs flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        le.event === 'paid'
                          ? 'bg-emerald-400'
                          : le.event === 'clicked'
                          ? 'bg-indigo-400'
                          : le.event === 'delivered'
                          ? 'bg-sky-400'
                          : 'bg-slate-400'
                      }`}
                    />
                    <div>
                      <span className="font-semibold text-white uppercase text-[11px] font-mono mr-2">
                        {le.event}
                      </span>
                      <span className="text-[11px] font-mono text-slate-400">Token: {le.token.slice(0, 10)}...</span>
                    </div>
                  </div>

                  <span className="text-[10px] text-slate-500 font-mono">{le.timestamp}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
