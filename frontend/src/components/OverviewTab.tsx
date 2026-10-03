import React, { useState } from 'react';
import {
  Phone,
  PhoneCall,
  CheckCircle2,
  Send,
  Calendar,
  AlertOctagon,
  XCircle,
  Clock,
  Play,
  Square,
  ShieldAlert,
  Loader2,
  Smartphone,
  RotateCcw,
  Save,
  Check,
} from 'lucide-react';
import type { Customer, Metrics, BatchProgress } from '../types';

interface OverviewTabProps {
  metrics: Metrics | null;
  customers: Customer[];
  activeCallId: string | null;
  batchProgress: BatchProgress | null;
  onCallCustomer: (customerId: string, phoneOverride?: string) => Promise<void>;
  onTriggerBatch: () => Promise<void>;
  onCancelBatch: () => Promise<void>;
  targetPhone: string;
  defaultPhone?: string;
  onTargetPhoneChange: (phone: string) => void;
  onResetTargetPhone: () => void;
  onSaveDefaultPhone?: (phone: string) => Promise<void>;
}

export const OverviewTab: React.FC<OverviewTabProps> = ({
  metrics,
  customers,
  activeCallId,
  batchProgress,
  onCallCustomer,
  onTriggerBatch,
  onCancelBatch,
  targetPhone,
  defaultPhone,
  onTargetPhoneChange,
  onResetTargetPhone,
  onSaveDefaultPhone,
}) => {
  const [dialingId, setDialingId] = useState<string | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [isSavingPhone, setIsSavingPhone] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const handleSingleCall = async (cid: string) => {
    setDialingId(cid);
    try {
      await onCallCustomer(cid, targetPhone);
    } finally {
      setDialingId(null);
    }
  };

  const handleSavePhone = async () => {
    if (!onSaveDefaultPhone || !targetPhone) return;
    setIsSavingPhone(true);
    try {
      await onSaveDefaultPhone(targetPhone);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (e: any) {
      alert(`Could not save default phone: ${e.message}`);
    } finally {
      setIsSavingPhone(false);
    }
  };

  const handleStartBatch = async () => {
    setBatchLoading(true);
    try {
      await onTriggerBatch();
    } finally {
      setBatchLoading(false);
    }
  };

  const getReasonBadge = (reason: string) => {
    switch (reason) {
      case 'insufficient_funds':
        return <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-amber-950/70 text-amber-300 border border-amber-800/40">Insufficient Funds</span>;
      case 'bank_timeout':
        return <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-sky-950/70 text-sky-300 border border-sky-800/40">Bank Timeout</span>;
      case 'mandate_expired':
        return <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-purple-950/70 text-purple-300 border border-purple-800/40">Mandate Expired</span>;
      case 'bank_decline':
      default:
        return <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-rose-950/70 text-rose-300 border border-rose-800/40">Bank Decline</span>;
    }
  };

  return (
    <div className="space-y-6">
      {/* ── 7 KPI Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        {/* Total Calls */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Total Calls</span>
            <Phone className="w-4 h-4 text-sky-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{metrics?.total_calls ?? 0}</div>
            <div className="text-[11px] text-slate-500 mt-0.5">Attempted records</div>
          </div>
        </div>

        {/* Recovered */}
        <div className="bg-slate-900 border border-emerald-900/40 rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-emerald-400 mb-2">
            <span className="text-xs font-medium">Total Recovered</span>
            <CheckCircle2 className="w-4 h-4" />
          </div>
          <div>
            <div className="text-2xl font-bold text-emerald-400">
              {metrics?.total_recovered ?? 0}
              <span className="text-xs font-normal text-emerald-500 ml-1.5">
                ({metrics?.recovery_rate ?? 0}%)
              </span>
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              {metrics?.recovered_count ?? 0} retry · {metrics?.paid_links_count ?? 0} link
            </div>
          </div>
        </div>

        {/* Links Sent */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Payment Links</span>
            <Send className="w-4 h-4 text-sky-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{metrics?.link_sent_count ?? 0}</div>
            <div className="text-[11px] text-slate-500 mt-0.5">Dispatched via SMS</div>
          </div>
        </div>

        {/* Scheduled */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Callbacks</span>
            <Calendar className="w-4 h-4 text-indigo-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{metrics?.scheduled_count ?? 0}</div>
            <div className="text-[11px] text-slate-500 mt-0.5">Scheduled slots</div>
          </div>
        </div>

        {/* Escalated */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Escalated</span>
            <AlertOctagon className="w-4 h-4 text-amber-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-amber-400">{metrics?.escalated_count ?? 0}</div>
            <div className="text-[11px] text-slate-500 mt-0.5">Dispute / Hardship</div>
          </div>
        </div>

        {/* Declined */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Declined</span>
            <XCircle className="w-4 h-4 text-rose-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-300">{metrics?.declined_count ?? 0}</div>
            <div className="text-[11px] text-slate-500 mt-0.5">Refused or DND</div>
          </div>
        </div>

        {/* Avg Duration */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Avg Duration</span>
            <Clock className="w-4 h-4 text-slate-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{metrics?.average_duration_sec ?? 0}s</div>
            <div className="text-[11px] text-slate-500 mt-0.5">Per call session</div>
          </div>
        </div>
      </div>

      {/* ── Live Phone Testing Destination Panel ── */}
      <div className="bg-gradient-to-r from-slate-900 via-slate-900 to-sky-950/40 border border-slate-800 rounded-xl p-4 shadow-lg">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center shrink-0 mt-0.5">
              <Smartphone className="w-5 h-5 text-sky-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-white">Live Phone Testing Destination</h3>
                {targetPhone && defaultPhone && targetPhone !== defaultPhone ? (
                  <span className="bg-purple-950 text-purple-300 border border-purple-800/60 text-[10px] px-2 py-0.5 rounded-full font-medium">
                    Custom Tester Number
                  </span>
                ) : (
                  <span className="bg-emerald-950 text-emerald-300 border border-emerald-800/60 text-[10px] px-2 py-0.5 rounded-full font-medium">
                    Default (Your Phone)
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                All outbound recovery calls & SMS payment links route to this phone so anyone evaluating can test the AI agent live on their own device.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Phone className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={targetPhone}
                onChange={(e) => onTargetPhoneChange(e.target.value)}
                placeholder="+91XXXXXXXXXX or 10 digits"
                className="bg-slate-950 border border-slate-700 focus:border-sky-500 focus:ring-1 focus:ring-sky-500 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white font-mono placeholder:text-slate-600 w-52 transition"
              />
            </div>

            {defaultPhone && targetPhone !== defaultPhone && (
              <button
                onClick={onResetTargetPhone}
                className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-2.5 py-1.5 rounded-lg border border-slate-700 transition flex items-center gap-1"
                title="Reset to default phone from server .env"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Reset
              </button>
            )}

            {onSaveDefaultPhone && (
              <button
                onClick={handleSavePhone}
                disabled={isSavingPhone || !targetPhone}
                className="text-xs bg-sky-600/20 hover:bg-sky-600/30 text-sky-300 border border-sky-500/30 px-3 py-1.5 rounded-lg font-medium transition flex items-center gap-1.5 disabled:opacity-50"
              >
                {saveSuccess ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-emerald-300">Saved</span>
                  </>
                ) : (
                  <>
                    <Save className="w-3.5 h-3.5" />
                    Set Default
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Batch Queue Manager ── */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col md:flex-row items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            Sequential Call Queue
            <span className="text-xs font-normal text-slate-400">(Dial each candidate customer in sequence with 5s delay)</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Safely routes one outbound call at a time to {targetPhone || defaultPhone || 'DEMO_PHONE'} with automated state transitions.
          </p>
        </div>

        <div className="flex items-center gap-3 w-full md:w-auto">
          {batchProgress && batchProgress.status === 'running' ? (
            <div className="flex items-center gap-3 w-full md:w-auto bg-slate-950 px-4 py-2 rounded-lg border border-slate-800">
              <div className="text-xs text-slate-300 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />
                <span>Progress: <strong>{batchProgress.completed} / {batchProgress.total}</strong> calls</span>
              </div>
              <button
                onClick={onCancelBatch}
                className="flex items-center gap-1 bg-rose-600 hover:bg-rose-500 text-white text-xs px-2.5 py-1 rounded font-medium transition"
              >
                <Square className="w-3 h-3" />
                Cancel Queue
              </button>
            </div>
          ) : (
            <button
              onClick={handleStartBatch}
              disabled={batchLoading || !!activeCallId}
              className="flex items-center justify-center gap-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs px-4 py-2 rounded-lg font-semibold shadow-md shadow-sky-600/20 transition w-full md:w-auto"
            >
              {batchLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-white" />}
              Call All Sequentially ({customers.length})
            </button>
          )}
        </div>
      </div>

      {/* ── Customer Roster Table ── */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">Target Customer Roster</h2>
            <p className="text-xs text-slate-400 mt-0.5">10 fictional Autopay recovery records with failure reasons and birth year verification</p>
          </div>
          <span className="text-xs text-slate-400 font-mono">10 records loaded</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/70 text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">ID</th>
                <th className="py-3 px-4">Customer Name</th>
                <th className="py-3 px-4">Target Phone</th>
                <th className="py-3 px-4">Bank</th>
                <th className="py-3 px-4">Amount Due</th>
                <th className="py-3 px-4">Due Date</th>
                <th className="py-3 px-4">Failure Reason</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {customers.map((c) => {
                const isDnd = !!c.do_not_call;
                const isDialingThis = dialingId === c.id;
                const isCallOngoing = activeCallId !== null;

                return (
                  <tr key={c.id} className="hover:bg-slate-800/30 transition">
                    <td className="py-3 px-4 font-mono font-medium text-slate-300">{c.id}</td>
                    <td className="py-3 px-4 font-semibold text-white">{c.name}</td>
                    <td className="py-3 px-4 font-mono text-slate-400">{c.phone_masked || c.phone}</td>
                    <td className="py-3 px-4 text-slate-300">{c.bank_name}</td>
                    <td className="py-3 px-4 font-semibold text-emerald-400">₹{c.amount_due.toLocaleString('en-IN')}</td>
                    <td className="py-3 px-4 font-mono text-slate-400">{c.due_date}</td>
                    <td className="py-3 px-4">{getReasonBadge(c.failure_reason)}</td>
                    <td className="py-3 px-4">
                      {isDnd ? (
                        <span className="inline-flex items-center gap-1 text-[11px] text-rose-400 font-medium">
                          <ShieldAlert className="w-3 h-3" />
                          Do Not Call
                        </span>
                      ) : c.last_outcome ? (
                        <span className="text-[11px] text-slate-400 font-mono">
                          {c.last_outcome}
                        </span>
                      ) : (
                        <span className="text-[11px] text-slate-500">Pending</span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={() => handleSingleCall(c.id)}
                        disabled={isDnd || isCallOngoing || isDialingThis}
                        className="inline-flex items-center gap-1 bg-sky-600/90 hover:bg-sky-500 disabled:opacity-30 disabled:cursor-not-allowed text-white text-xs px-3 py-1.5 rounded font-medium shadow-sm transition"
                      >
                        {isDialingThis ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <PhoneCall className="w-3.5 h-3.5" />
                        )}
                        Call
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
