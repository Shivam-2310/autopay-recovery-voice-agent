export interface SystemConfig {
  demo_phone_masked: string;
  demo_override: boolean;
  in_call_window: boolean;
  call_window_status: string;
  sms_mode: 'twilio' | 'mock';
  voice_id: string;
  llm_provider: string;
  livekit_url: string;
}

export interface Customer {
  id: string;
  name: string;
  phone: string;
  phone_masked: string;
  bank_name: string;
  amount_due: number;
  due_date: string;
  failure_reason: string;
  do_not_call: boolean | number;
  last_call_at?: string;
  last_outcome?: string;
}

export interface CallRecord {
  id: string;
  customer_id: string;
  customer_name?: string;
  phone_masked?: string;
  bank_name?: string;
  amount_due?: number;
  source: 'live' | 'simulated';
  status: 'active' | 'completed' | 'failed';
  outcome?: string;
  duration_sec: number;
  note?: string;
  started_at: string;
  ended_at?: string;
  transcript?: string;
}

export interface Metrics {
  total_calls: number;
  total_recovered: number;
  recovered_count: number;
  paid_links_count: number;
  link_sent_count: number;
  scheduled_count: number;
  escalated_count: number;
  declined_count: number;
  verification_failed_count?: number;
  wrong_party_count?: number;
  no_answer_count?: number;
  recovery_rate: number;
  average_duration_sec: number;
}

export interface Turn {
  id: string;
  speaker: 'agent' | 'customer';
  text: string;
  is_final: boolean;
  timestamp: string;
}

export interface GuardrailEvent {
  id: number;
  name: string;
  action: string;
  detail?: string;
  timestamp: string;
}

export interface ToolCallEvent {
  tool: string;
  status: string;
  customer_id: string;
  timestamp: string;
}

export interface MessageEvent {
  sid: string;
  call_id: string;
  status: string;
  to_masked?: string;
  mode?: string;
  error_code?: string;
  error_message?: string;
  url?: string;
  timestamp: string;
}

export interface LinkEvent {
  token: string;
  call_id: string;
  event: string;
  timestamp: string;
}

export interface BatchProgress {
  batch_id: string;
  completed: number;
  total: number;
  status?: string;
}
