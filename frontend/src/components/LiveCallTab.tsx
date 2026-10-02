import React, { useState, useEffect, useRef } from 'react';
import {
  PhoneOff,
  Radio,
  User,
  Bot,
  Volume2,
  VolumeX,
  ShieldAlert,
  Wrench,
  CheckCircle,
  AlertTriangle,
  Loader2,
  Clock,
  Sparkles,
} from 'lucide-react';
import { Room, RoomEvent, RemoteTrack } from 'livekit-client';
import type { Turn, GuardrailEvent, ToolCallEvent } from '../types';
import { fetchListenToken } from '../api';

interface LiveCallTabProps {
  callId: string | null;
  customerName: string;
  status: string;
  callState: {
    stage: string;
    verified: boolean;
    verification_attempts: number;
    offers_made: number;
    terminal_outcome?: string;
    outcome_note?: string;
    do_not_call?: boolean;
  };
  turns: Turn[];
  guardrails: GuardrailEvent[];
  toolCalls: ToolCallEvent[];
  onEndCall: (callId: string) => Promise<void>;
}

export const LiveCallTab: React.FC<LiveCallTabProps> = ({
  callId,
  customerName,
  status,
  callState,
  turns,
  guardrails,
  toolCalls,
  onEndCall,
}) => {
  const [durationSec, setDurationSec] = useState(0);
  const [isEnding, setIsEnding] = useState(false);

  // Live Listen WebRTC State (Step 8)
  const [isListening, setIsListening] = useState(false);
  const [isConnectingAudio, setIsConnectingAudio] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(0.85);
  const [audioActive, setAudioActive] = useState(false);

  const roomRef = useRef<Room | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Duration Timer
  useEffect(() => {
    if (!callId || status !== 'active') {
      setDurationSec(0);
      return;
    }
    const interval = window.setInterval(() => {
      setDurationSec((prev) => prev + 1);
    }, 1000);
    return () => window.clearInterval(interval);
  }, [callId, status]);

  // Auto-scroll transcript
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns]);

  // Live Listen Audio Lifecycle (Step 8)
  const startLiveListen = async () => {
    if (!callId) return;
    setIsConnectingAudio(true);
    try {
      const data = await fetchListenToken(callId);
      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });
      roomRef.current = room;

      room.on(
        RoomEvent.TrackSubscribed,
        (track: RemoteTrack) => {
          if (track.kind === 'audio') {
            const el = track.attach();
            el.volume = isMuted ? 0 : volume;
            audioElementRef.current = el;
            setAudioActive(true);
          }
        }
      );

      room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
        track.detach();
        setAudioActive(false);
      });

      room.on(RoomEvent.Disconnected, () => {
        setIsListening(false);
        setAudioActive(false);
      });

      await room.connect(data.url, data.token);
      setIsListening(true);
    } catch (e) {
      console.error('Failed to connect live listen audio:', e);
      alert('Could not attach live listen audio monitor. Ensure LiveKit is reachable.');
    } finally {
      setIsConnectingAudio(false);
    }
  };

  const stopLiveListen = () => {
    if (roomRef.current) {
      roomRef.current.disconnect();
      roomRef.current = null;
    }
    if (audioElementRef.current) {
      audioElementRef.current.remove();
      audioElementRef.current = null;
    }
    setIsListening(false);
    setAudioActive(false);
  };

  // Handle Mute & Volume
  const toggleMute = () => {
    const next = !isMuted;
    setIsMuted(next);
    if (audioElementRef.current) {
      audioElementRef.current.volume = next ? 0 : volume;
    }
  };

  const handleVolumeChange = (newVol: number) => {
    setVolume(newVol);
    if (audioElementRef.current && !isMuted) {
      audioElementRef.current.volume = newVol;
    }
  };

  // Cleanup on unmount or call finish
  useEffect(() => {
    return () => {
      stopLiveListen();
    };
  }, []);

  useEffect(() => {
    if (status !== 'active') {
      stopLiveListen();
    }
  }, [status]);

  const formatTimer = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const handleEnd = async () => {
    if (!callId) return;
    setIsEnding(true);
    try {
      await onEndCall(callId);
    } finally {
      setIsEnding(false);
    }
  };

  if (!callId) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-12 text-center max-w-xl mx-auto my-8">
        <div className="w-16 h-16 rounded-full bg-slate-800 flex items-center justify-center mx-auto mb-4 text-slate-500">
          <Radio className="w-8 h-8" />
        </div>
        <h3 className="text-base font-semibold text-white">No Outbound Call in Progress</h3>
        <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
          Navigate to the Overview tab and click "Call" on any customer, or start the sequential queue.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* ── Left Column: Telemetry & State Panel (1 Col) ── */}
      <div className="space-y-4 lg:col-span-1">
        {/* Active Call Header Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800/60">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
              LIVE TELEPHONY
            </span>
            <div className="flex items-center gap-1 text-slate-300 text-xs font-mono font-medium bg-slate-950 px-2 py-1 rounded">
              <Clock className="w-3.5 h-3.5 text-sky-400" />
              {formatTimer(durationSec)}
            </div>
          </div>

          <h2 className="text-base font-bold text-white tracking-tight">{customerName || 'Customer'}</h2>
          <div className="text-[11px] font-mono text-slate-400 truncate mt-0.5">{callId}</div>

          <div className="mt-4 pt-4 border-t border-slate-800 flex items-center justify-between">
            <span className="text-xs text-slate-400 capitalize">Status: <strong className="text-white">{status}</strong></span>
            <button
              onClick={handleEnd}
              disabled={isEnding || status !== 'active'}
              className="flex items-center gap-1.5 bg-rose-600/90 hover:bg-rose-500 disabled:opacity-40 text-white text-xs px-3 py-1.5 rounded-lg font-medium shadow-sm transition"
            >
              {isEnding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PhoneOff className="w-3.5 h-3.5" />}
              End Call
            </button>
          </div>
        </div>

        {/* Live Listen WebRTC Audio Monitor (Step 8) */}
        <div className="bg-slate-900 border border-indigo-900/50 rounded-xl p-4 shadow-lg shadow-indigo-950/20">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-indigo-300">
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              Live Listen WebRTC Monitor
            </div>
            {audioActive && (
              <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Receiving PCM Audio
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-400 mb-3">
            Hidden, subscribe-only audio stream directly from the LiveKit room.
          </p>

          {!isListening ? (
            <button
              onClick={startLiveListen}
              disabled={isConnectingAudio}
              className="w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs py-2 rounded-lg font-semibold transition shadow-md shadow-indigo-600/20"
            >
              {isConnectingAudio ? <Loader2 className="w-4 h-4 animate-spin" /> : <Volume2 className="w-4 h-4" />}
              Start Listening In
            </button>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2 bg-slate-950 px-3 py-2 rounded-lg border border-slate-800">
                <button
                  onClick={toggleMute}
                  className="text-slate-400 hover:text-white transition p-1"
                >
                  {isMuted ? <VolumeX className="w-4 h-4 text-rose-400" /> : <Volume2 className="w-4 h-4 text-sky-400" />}
                </button>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={isMuted ? 0 : volume}
                  onChange={(e) => handleVolumeChange(parseFloat(e.target.value))}
                  className="w-full accent-sky-500 h-1.5 bg-slate-800 rounded-lg cursor-pointer"
                />
                <span className="text-[11px] font-mono text-slate-400 w-8 text-right">
                  {isMuted ? '0%' : `${Math.round(volume * 100)}%`}
                </span>
              </div>

              <button
                onClick={stopLiveListen}
                className="w-full text-xs text-slate-400 hover:text-slate-200 py-1 transition"
              >
                Disconnect Audio Monitor
              </button>
            </div>
          )}
        </div>

        {/* Runtime CallState Panel */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
            In-Memory CallState
          </h3>

          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Call Stage:</span>
              <span className="font-mono font-semibold text-sky-400 uppercase">{callState.stage}</span>
            </div>

            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Identity Verified:</span>
              <span className={`font-semibold px-2 py-0.5 rounded text-[11px] ${callState.verified ? 'bg-emerald-950 text-emerald-300' : 'bg-amber-950 text-amber-300'}`}>
                {callState.verified ? '✓ Verified' : 'Pending Verification'}
              </span>
            </div>

            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Verification Attempts:</span>
              <span className="font-mono text-slate-200">{callState.verification_attempts} / 2</span>
            </div>

            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Offers Presented:</span>
              <span className="font-mono text-slate-200">{callState.offers_made} / 2</span>
            </div>

            {callState.do_not_call && (
              <div className="flex items-center justify-between py-1 border-b border-slate-800/60 text-rose-400">
                <span className="flex items-center gap-1 font-semibold">
                  <ShieldAlert className="w-3.5 h-3.5" /> DND Requested:
                </span>
                <span className="font-mono">Yes</span>
              </div>
            )}

            {callState.terminal_outcome && (
              <div className="pt-2">
                <span className="text-slate-400 block mb-1">Terminal Outcome:</span>
                <div className="bg-slate-950 px-2.5 py-1.5 rounded border border-slate-800 font-mono text-emerald-400 font-semibold text-[11px]">
                  {callState.terminal_outcome}
                  {callState.outcome_note && (
                    <div className="text-[10px] text-slate-400 font-normal mt-0.5">{callState.outcome_note}</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Tool Invocations Chips */}
        {toolCalls.length > 0 && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Wrench className="w-3.5 h-3.5 text-sky-400" />
              Tool Calls ({toolCalls.length})
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {toolCalls.map((t, idx) => (
                <span
                  key={idx}
                  className="bg-slate-950 text-slate-300 border border-slate-800 text-[11px] font-mono px-2 py-0.5 rounded flex items-center gap-1"
                >
                  <CheckCircle className="w-3 h-3 text-emerald-400" />
                  {t.tool}()
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Guardrail Events Feed */}
        {guardrails.length > 0 && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
              Guardrail Activations ({guardrails.length})
            </h3>
            <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
              {guardrails.map((g, idx) => (
                <div
                  key={idx}
                  className="bg-slate-950 border border-amber-900/30 rounded px-2 py-1 text-[11px] text-amber-300 flex items-start gap-1.5"
                >
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold font-mono">G{g.id}: {g.name}</span>
                    <div className="text-[10px] text-slate-400">{g.action} {g.detail ? `· ${g.detail}` : ''}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Right Column: Streaming Transcript Chat (2 Cols) ── */}
      <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl flex flex-col h-[700px] overflow-hidden shadow-xl">
        <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between bg-slate-950/70">
          <div>
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              Streaming Transcript
              <span className="text-[10px] text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800/40">
                PII Redacted & Sanitized
              </span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">Zero markdown · Spoken English normalization · Birth years withheld</p>
          </div>
          <span className="text-xs text-slate-400 font-mono">{turns.length} turns</span>
        </div>

        {/* Chat History View */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-950/30">
          {turns.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 text-xs">
              <Loader2 className="w-6 h-6 animate-spin text-sky-400 mb-2" />
              <span>Awaiting phone connection and speech stream...</span>
            </div>
          ) : (
            turns.map((turn, idx) => {
              const isAgent = turn.speaker === 'agent';
              return (
                <div
                  key={turn.id || idx}
                  className={`flex items-start gap-2.5 ${isAgent ? 'justify-start' : 'justify-end'}`}
                >
                  {isAgent && (
                    <div className="w-7 h-7 rounded-full bg-sky-600/90 text-white flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
                      <Bot className="w-4 h-4" />
                    </div>
                  )}

                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-xs leading-relaxed shadow-md ${
                      isAgent
                        ? 'bg-slate-800 text-slate-100 rounded-tl-sm border border-slate-700/60'
                        : 'bg-sky-600 text-white rounded-tr-sm'
                    }`}
                  >
                    <div className="font-semibold text-[10px] uppercase tracking-wider mb-1 opacity-70">
                      {isAgent ? 'Aanya (AI Assistant)' : 'Customer'}
                    </div>
                    <div className="whitespace-pre-wrap">{turn.text}</div>
                  </div>

                  {!isAgent && (
                    <div className="w-7 h-7 rounded-full bg-slate-700 text-slate-200 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
                      <User className="w-4 h-4" />
                    </div>
                  )}
                </div>
              );
            })
          )}
          <div ref={chatEndRef} />
        </div>
      </div>
    </div>
  );
};
