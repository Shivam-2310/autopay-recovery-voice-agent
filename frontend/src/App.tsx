import { useState, useEffect, useCallback } from 'react';
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

  useEffect(() => {
    loadData();
  }, [loadData]);

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
          // If server has more or different turns, merge
          const serverTurns: Turn[] = details.turns.map((t: any, idx: number) => ({
            id: `turn_db_${idx}_${t.timestamp || idx}`,
            speaker: t.speaker === 'customer' ? 'customer' : 'agent',
            text: t.text || '',
            is_final: Boolean(t.is_final),
            timestamp: t.timestamp || new Date().toLocaleTimeString(),
          }));
          if (serverTurns.length >= prev.length) {
            return serverTurns;
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
          if (last.speaker === speaker && last.text.toLowerCase() === text.toLowerCase()) {
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
    } else if (type === 'link.event') {
      const lItem: LinkEvent = {
        token: msg.token || msg.payload?.token || '',
        call_id: msg.call_id || '',
        event: msg.event || msg.payload?.event || '',
        timestamp: msg.timestamp || now,
      };
      setLinkEvents((prev) => [lItem, ...prev]);
      if (msg.event === 'paid') {
        fetchCalls().then(setCalls);
        fetchMetrics().then(setMetrics);
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
    }
  }, []);

  const { status: wsStatus } = useWebSocket({
    onMessage: handleWsMessage,
  });

  // Action Handlers
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
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">
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
