import { useState, useEffect, useCallback } from 'react';
import { CheckCircle2, X } from 'lucide-react';
import { Header } from './components/Header';
import { OverviewTab } from './components/OverviewTab';
import { LiveCallTab } from './components/LiveCallTab';
import { MessagesTab } from './components/MessagesTab';
import { HistoryTab } from './components/HistoryTab';
import { useWebSocket } from './hooks/useWebSocket';
import {
  fetchConfig,
  fetchCustomers,
  fetchCalls,
  fetchMetrics,
  fetchCallDetails,
  triggerCall,
  triggerBatchCalls,
  cancelBatchCalls,
  endCall,
  resetDemoData,
} from './api';
import type {
  SystemConfig,
  Customer,
  CallRecord,
  Metrics,
  Turn,
  GuardrailEvent,
  ToolCallEvent,
  MessageEvent,
  LinkEvent,
  BatchProgress,
} from './types';

export function App() {
  const [activeTab, setActiveTab] = useState<'overview' | 'live' | 'messages' | 'history'>('overview');
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [calls, setCalls] = useState<CallRecord[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);

  // Real-time payment notification banner
  const [paymentNotification, setPaymentNotification] = useState<{
    customerName?: string;
    amount?: number;
    message?: string;
    token?: string;
  } | null>(null);

  // Active call state
  const [activeCallId, setActiveCallId] = useState<string | null>(null);
  const [activeCustomerName, setActiveCustomerName] = useState<string>('');
  const [activeCallStatus, setActiveCallStatus] = useState<string>('idle');
  const [callState, setCallState] = useState({
    stage: 'init',
    verified: false,
    verification_attempts: 0,
    offers_made: 0,
    terminal_outcome: undefined as string | undefined,
    outcome_note: undefined as string | undefined,
    do_not_call: false,
  });

  const [turns, setTurns] = useState<Turn[]>([]);
  const [guardrails, setGuardrails] = useState<GuardrailEvent[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallEvent[]>([]);
  const [messages, setMessages] = useState<MessageEvent[]>([]);
  const [linkEvents, setLinkEvents] = useState<LinkEvent[]>([]);
  const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(null);

  // Load initial data
  const loadData = useCallback(async () => {
    try {
      const [cfg, custs, cls, mets] = await Promise.all([
        fetchConfig(),
        fetchCustomers(),
        fetchCalls(),
        fetchMetrics(),
      ]);
      setConfig(cfg);
      setCustomers(custs);
      setCalls(cls);
      setMetrics(mets);
    } catch (err) {
      console.error('Failed to load initial data:', err);
    }
  }, []);

  // Dynamic background polling (every 4s) to ensure dashboard metrics, calls, and customer statuses stay live
  useEffect(() => {
    loadData();
    const pollTimer = window.setInterval(() => {
      fetchMetrics().then(setMetrics).catch(() => {});
      fetchCalls().then(setCalls).catch(() => {});
      fetchCustomers().then(setCustomers).catch(() => {});
    }, 4000);
    return () => window.clearInterval(pollTimer);
  }, [loadData]);

  // Auto-dismiss payment notification banner after 10 seconds
  useEffect(() => {
    if (!paymentNotification) return;
    const timer = setTimeout(() => {
      setPaymentNotification(null);
    }, 10000);
    return () => clearTimeout(timer);
  }, [paymentNotification]);

  // Sync active call details from backend (hydrates turns, tool calls, guardrails)
  const syncCallDetails = useCallback(async (callId: string) => {
    if (!callId) return;
    try {
      const details = await fetchCallDetails(callId);
      if (!details) return;

      if (details.customer_name && !activeCustomerName) {
        setActiveCustomerName(details.customer_name);
      }

      if (Array.isArray(details.turns) && details.turns.length > 0) {
        setTurns((prev) => {
          const rawServerTurns: Turn[] = details.turns.map((t: any, idx: number) => ({
            id: `turn_db_${idx}_${t.timestamp || idx}`,
            speaker: t.speaker === 'customer' ? 'customer' : 'agent',
            text: t.text || '',
            is_final: Boolean(t.is_final),
            timestamp: t.timestamp || new Date().toLocaleTimeString(),
          }));

          // Strict consecutive deduplication for turns
          const dedupedServer: Turn[] = [];
          for (const st of rawServerTurns) {
            const stNorm = st.text.toLowerCase().replace(/[^\w\s]/g, '').trim();
            if (!stNorm) continue;
            if (dedupedServer.length > 0) {
              const last = dedupedServer[dedupedServer.length - 1];
              const lastNorm = last.text.toLowerCase().replace(/[^\w\s]/g, '').trim();
              if (last.speaker === st.speaker && lastNorm === stNorm) {
                continue;
              }
            }
            dedupedServer.push(st);
          }

          if (dedupedServer.length >= prev.length) {
            return dedupedServer;
          }
          return prev;
        });
      }

      if (Array.isArray(details.events) && details.events.length > 0) {
        const restoredGuardrails: GuardrailEvent[] = [];
        const restoredToolCalls: ToolCallEvent[] = [];
        for (const ev of details.events) {
          const p = ev.payload || {};
          if (ev.event_type === 'guardrail.triggered') {
            restoredGuardrails.push({
              id: p.id || 0,
              name: p.name || 'Guardrail',
              action: p.action || 'triggered',
              detail: p.detail || p.error,
              timestamp: ev.timestamp || '',
            });
          } else if (ev.event_type === 'tool.call') {
            restoredToolCalls.push({
              tool: p.tool || 'unknown_tool',
              status: p.status || 'success',
              customer_id: p.customer_id || '',
              timestamp: ev.timestamp || '',
            });
          }
        }
        if (restoredGuardrails.length > 0) {
          setGuardrails(restoredGuardrails);
        }
        if (restoredToolCalls.length > 0) {
          setToolCalls(restoredToolCalls);
        }
      }
    } catch (e) {
      // quiet debug log
      console.debug('syncCallDetails error:', e);
    }
  }, [activeCustomerName]);

  // Periodic polling for active call to guarantee live transcript sync
  useEffect(() => {
    if (activeCallStatus !== 'active' || !activeCallId) return;
    const interval = window.setInterval(() => {
      syncCallDetails(activeCallId);
    }, 2000);
    return () => window.clearInterval(interval);
  }, [activeCallStatus, activeCallId, syncCallDetails]);

  // WebSocket message dispatcher
  const handleWsMessage = useCallback((msg: any) => {
    const type = msg.type;
    const now = new Date().toLocaleTimeString();

    if (type === 'call.status') {
      const cid = msg.call_id;
      const status = msg.status || msg.payload?.status || 'active';
      if (status === 'active') {
        setActiveCallId(cid);
        setActiveCallStatus('active');
        setActiveTab('live');
        // Hydrate from DB immediately
        syncCallDetails(cid);
      } else if (status === 'completed' || status === 'terminated') {
        setActiveCallStatus('completed');
        if (cid) syncCallDetails(cid);
        fetchCalls().then(setCalls);
        fetchMetrics().then(setMetrics);
        fetchCustomers().then(setCustomers);
      }
    } else if (type === 'turn') {
      const p = msg.payload || {};
      const speaker = p.speaker === 'customer' ? 'customer' : 'agent';
      const text = (p.text || '').trim();
      if (!text) return;

      const norm = text.toLowerCase().replace(/[^\w\s]/g, '').trim();
      if (!norm) return;

      const newTurn: Turn = {
        id: `turn_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
        speaker,
        text,
        is_final: p.is_final ?? true,
        timestamp: msg.timestamp || now,
      };

      setTurns((prev) => {
        // Prevent duplicate append of identical message from same speaker
        if (prev.length > 0) {
          const last = prev[prev.length - 1];
          const lastNorm = last.text.toLowerCase().replace(/[^\w\s]/g, '').trim();
          if (last.speaker === speaker && lastNorm === norm) {
            return prev;
          }
        }
        return [...prev, newTurn];
      });
    } else if (type === 'tool.call') {
      const p = msg.payload || {};
      setToolCalls((prev) => [
        ...prev,
        {
          tool: p.tool || 'unknown_tool',
          status: p.status || 'success',
          customer_id: p.customer_id || '',
          timestamp: msg.timestamp || now,
        },
      ]);
    } else if (type === 'guardrail.triggered') {
      const p = msg.payload || {};
      setGuardrails((prev) => [
        ...prev,
        {
          id: p.id || 0,
          name: p.name || 'Guardrail',
          action: p.action || 'triggered',
          detail: p.detail || p.error,
          timestamp: msg.timestamp || now,
        },
      ]);
    } else if (type === 'state.update') {
      const p = msg.payload || {};
      setCallState((prev) => ({
        ...prev,
        stage: p.stage || prev.stage,
        verified: p.verified !== undefined ? p.verified : prev.verified,
        verification_attempts: p.verification_attempts ?? prev.verification_attempts,
        offers_made: p.offers_made ?? prev.offers_made,
        terminal_outcome: p.terminal_outcome ?? prev.terminal_outcome,
        outcome_note: p.outcome_note ?? prev.outcome_note,
        do_not_call: p.do_not_call !== undefined ? p.do_not_call : prev.do_not_call,
      }));
    } else if (type === 'message.status') {
      const mItem: MessageEvent = {
        sid: msg.sid || msg.payload?.sid || 'unknown',
        call_id: msg.call_id || '',
        status: msg.status || msg.payload?.status || 'sent',
        error_code: msg.error_code || msg.payload?.error_code,
        url: msg.url || msg.payload?.url,
        timestamp: msg.timestamp || now,
      };
      setMessages((prev) => [mItem, ...prev.filter((m) => m.sid !== mItem.sid)]);
    } else if (type === 'payment.confirmed') {
      const custName = msg.customer_name || 'Customer';
      const amt = msg.amount || undefined;
      const textMsg = msg.message || `Payment of ₹${amt || ''} received from ${custName} via SMS link`;
      setPaymentNotification({
        customerName: custName,
        amount: amt,
        message: textMsg,
        token: msg.token,
      });
      setCallState((prev) => ({
        ...prev,
        stage: 'resolved',
        terminal_outcome: 'recovered',
        outcome_note: textMsg,
      }));
      fetchCalls().then(setCalls);
      fetchMetrics().then(setMetrics);
      fetchCustomers().then(setCustomers);
    } else if (type === 'link.event') {
      const lItem: LinkEvent = {
        token: msg.token || msg.payload?.token || '',
        call_id: msg.call_id || '',
        event: msg.event || msg.payload?.event || '',
        timestamp: msg.timestamp || now,
      };
      setLinkEvents((prev) => [lItem, ...prev]);
      if (msg.event === 'paid') {
        const custName = msg.customer_name || 'Customer';
        const amt = msg.amount || undefined;
        setPaymentNotification({
          customerName: custName,
          amount: amt,
          message: `Payment confirmed from ${custName} via SMS link`,
          token: msg.token,
        });
        setCallState((prev) => ({
          ...prev,
          stage: 'resolved',
          terminal_outcome: 'recovered',
          outcome_note: `Paid via SMS link`,
        }));
        fetchCalls().then(setCalls);
        fetchMetrics().then(setMetrics);
        fetchCustomers().then(setCustomers);
      }
    } else if (type === 'batch.progress') {
      setBatchProgress({
        batch_id: msg.batch_id,
        completed: msg.completed,
        total: msg.total,
        status: 'running',
      });
      if (msg.completed === msg.total) {
        setTimeout(() => setBatchProgress(null), 3000);
      }
    } else if (type === 'call.ended') {
      setActiveCallStatus('completed');
      fetchCalls().then(setCalls);
      fetchMetrics().then(setMetrics);
      fetchCustomers().then(setCustomers);
    } else if (type === 'demo.reset') {
      setCalls([]);
      setTurns([]);
      setGuardrails([]);
      setToolCalls([]);
      setMessages([]);
      setLinkEvents([]);
      setActiveCallId(null);
      setActiveCallStatus('idle');
      setPaymentNotification(null);
      setBatchProgress(null);
      setCallState({
        stage: 'init',
        verified: false,
        verification_attempts: 0,
        offers_made: 0,
        terminal_outcome: undefined,
        outcome_note: undefined,
        do_not_call: false,
      });
      fetchCalls().then(setCalls);
      fetchMetrics().then(setMetrics);
      fetchCustomers().then(setCustomers);
    }
  }, []);

  const { status: wsStatus } = useWebSocket({
    onMessage: handleWsMessage,
  });

  // Action Handlers
  const handleResetDemo = async () => {
    try {
      await resetDemoData();
      setCalls([]);
      setTurns([]);
      setGuardrails([]);
      setToolCalls([]);
      setMessages([]);
      setLinkEvents([]);
      setActiveCallId(null);
      setActiveCallStatus('idle');
      setPaymentNotification(null);
      setBatchProgress(null);
      setCallState({
        stage: 'init',
        verified: false,
        verification_attempts: 0,
        offers_made: 0,
        terminal_outcome: undefined,
        outcome_note: undefined,
        do_not_call: false,
      });
      await Promise.all([
        fetchCalls().then(setCalls),
        fetchMetrics().then(setMetrics),
        fetchCustomers().then(setCustomers),
      ]);
    } catch (err: any) {
      alert(`Could not reset demo data: ${err.message}`);
    }
  };

  const handleCallCustomer = async (customerId: string) => {
    const cust = customers.find((c) => c.id === customerId);
    setActiveCustomerName(cust?.name || customerId);
    try {
      const res = await triggerCall(customerId);
      setActiveCallId(res.call_id);
      setActiveCallStatus('active');
      setActiveTab('live');
    } catch (e: any) {
      alert(`Could not start call: ${e.message}`);
    }
  };

  const handleTriggerBatch = async () => {
    try {
      const res = await triggerBatchCalls(undefined, 5.0);
      setBatchProgress({
        batch_id: res.batch_id,
        completed: 0,
        total: res.total_queued,
        status: 'running',
      });
    } catch (e: any) {
      alert(`Could not start sequential batch: ${e.message}`);
    }
  };

  const handleCancelBatch = async () => {
    if (!batchProgress) return;
    try {
      await cancelBatchCalls(batchProgress.batch_id);
      setBatchProgress(null);
    } catch (e: any) {
      console.error('Cancel batch error:', e);
    }
  };

  const handleEndCall = async (callIdToEnd: string) => {
    try {
      await endCall(callIdToEnd);
      setActiveCallStatus('completed');
    } catch (e: any) {
      console.error('End call error:', e);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header
        config={config}
        wsStatus={wsStatus}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        hasActiveCall={activeCallStatus === 'active'}
        onResetDemo={handleResetDemo}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">
        {/* Real-time Payment Confirmation Alert */}
        {paymentNotification && (
          <div className="mb-6 bg-gradient-to-r from-emerald-950/90 via-emerald-900/80 to-slate-900 border border-emerald-500/60 rounded-xl p-4 shadow-xl flex items-center justify-between transition-all">
            <div className="flex items-center gap-3.5">
              <div className="w-10 h-10 rounded-full bg-emerald-500/20 border border-emerald-500/50 flex items-center justify-center text-emerald-400 shrink-0">
                <CheckCircle2 className="w-6 h-6 animate-pulse" />
              </div>
              <div>
                <div className="text-sm font-bold text-white flex items-center gap-2">
                  <span>Payment Confirmed via SMS Link!</span>
                  {paymentNotification.amount !== undefined && paymentNotification.amount > 0 && (
                    <span className="bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded text-xs border border-emerald-500/30 font-semibold font-mono">
                      ₹{paymentNotification.amount.toLocaleString('en-IN')}
                    </span>
                  )}
                </div>
                <p className="text-xs text-emerald-200/90 mt-0.5">
                  {paymentNotification.message || `Account settled for ${paymentNotification.customerName || 'customer'}. Dashboard metrics updated dynamically.`}
                </p>
              </div>
            </div>
            <button
              onClick={() => setPaymentNotification(null)}
              className="text-emerald-400/80 hover:text-white p-1.5 rounded-lg hover:bg-emerald-800/40 transition shrink-0"
              title="Dismiss"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        )}

        {activeTab === 'overview' && (
          <OverviewTab
            metrics={metrics}
            customers={customers}
            activeCallId={activeCallStatus === 'active' ? activeCallId : null}
            batchProgress={batchProgress}
            onCallCustomer={handleCallCustomer}
            onTriggerBatch={handleTriggerBatch}
            onCancelBatch={handleCancelBatch}
            demoPhone={config?.demo_phone}
          />
        )}

        {activeTab === 'live' && (
          <LiveCallTab
            callId={activeCallId}
            customerName={activeCustomerName}
            status={activeCallStatus}
            callState={callState}
            turns={turns}
            guardrails={guardrails}
            toolCalls={toolCalls}
            onEndCall={handleEndCall}
          />
        )}

        {activeTab === 'messages' && (
          <MessagesTab
            messages={messages}
            linkEvents={linkEvents}
            smsMode={config?.sms_mode || 'mock'}
          />
        )}

        {activeTab === 'history' && (
          <HistoryTab
            calls={calls}
            onRefresh={loadData}
          />
        )}
      </main>

      <footer className="border-t border-slate-900 bg-slate-950 py-3 text-center text-xs text-slate-500">
        PayEase Autopay Recovery Voice Agent · LiveKit WebRTC + Deepgram + ElevenLabs
      </footer>
    </div>
  );
}

export default App;
