import type { SystemConfig, Customer, CallRecord, Metrics } from './types';

const BASE_URL = ''; // Relative paths proxy via Vite server

export async function fetchConfig(): Promise<SystemConfig> {
  const res = await fetch(`${BASE_URL}/api/config`);
  if (!res.ok) throw new Error(`Failed to load system config: ${res.statusText}`);
  return res.json();
}

export async function fetchCustomers(): Promise<Customer[]> {
  const res = await fetch(`${BASE_URL}/api/customers`);
  if (!res.ok) throw new Error(`Failed to load customers: ${res.statusText}`);
  return res.json();
}

export async function fetchCalls(limit: number = 50): Promise<CallRecord[]> {
  const res = await fetch(`${BASE_URL}/api/calls?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to load calls: ${res.statusText}`);
  return res.json();
}

export async function fetchCallDetails(callId: string): Promise<any> {
  const res = await fetch(`${BASE_URL}/api/calls/${callId}`);
  if (!res.ok) throw new Error(`Failed to load call details: ${res.statusText}`);
  return res.json();
}

export async function fetchMetrics(): Promise<Metrics> {
  const res = await fetch(`${BASE_URL}/api/metrics`);
  if (!res.ok) throw new Error(`Failed to load metrics: ${res.statusText}`);
  return res.json();
}

export async function triggerCall(customerId: string, phoneNumber?: string): Promise<{ call_id: string; room_name: string; status: string; target_phone_masked?: string }> {
  const res = await fetch(`${BASE_URL}/api/calls`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customer_id: customerId, phone_number: phoneNumber || undefined }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || 'Failed to dispatch call');
  }
  return res.json();
}

export async function updateDefaultPhone(phoneNumber: string): Promise<{ status: string; demo_phone: string; demo_phone_masked: string }> {
  const res = await fetch(`${BASE_URL}/api/config/phone`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone_number: phoneNumber }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || 'Failed to update phone number');
  }
  return res.json();
}

export async function triggerBatchCalls(customerIds?: string[], delaySec: number = 5.0): Promise<{ batch_id: string; status: string; total_queued: number }> {
  const res = await fetch(`${BASE_URL}/api/calls/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customer_ids: customerIds, delay_sec: delaySec }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || 'Failed to trigger batch calls');
  }
  return res.json();
}

export async function cancelBatchCalls(batchId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/api/batch/${batchId}/cancel`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed to cancel batch ${batchId}`);
  return res.json();
}

export async function endCall(callId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/api/calls/${callId}/end`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed to end call ${callId}`);
  return res.json();
}

export async function fetchListenToken(callId: string): Promise<{ token: string; url: string; room: string }> {
  const res = await fetch(`${BASE_URL}/api/calls/${callId}/listen-token`);
  if (!res.ok) throw new Error(`Failed to fetch listen token for ${callId}`);
  return res.json();
}
