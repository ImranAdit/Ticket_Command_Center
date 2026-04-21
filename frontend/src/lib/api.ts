import axios from 'axios';

export const BACKEND_URL = import.meta.env.VITE_API_URL as string;

if (!BACKEND_URL) {
  throw new Error("VITE_API_URL is not set. Check your environment variables.");
}
});

// ─── Legacy CSV classify (kept for backward compat) ───────────────────────
export interface TicketData {
    id: string | number;
    status: string;
    created_at: string;
    modified_at?: string;
    team?: string;
    agent?: string;
    subject?: string;
}

export interface MetricResult {
    id: string;
    metrics: {
        biz_hours_idle: number;
        biz_days_idle: number;
        alert_class: string;
        is_today: boolean;
        is_pending_dev: boolean;
    };
}

export const classifyTickets = async (tickets: TicketData[]): Promise<MetricResult[]> => {
    const response = await api.post('/api/logic/classify', { tickets });
    return response.data.results;
};

// ─── SLA Breach types ─────────────────────────────────────────────────────
export type Severity = 'critical' | 'moderate' | 'watch' | 'normal';
export type Priority = 'High' | 'Medium' | 'Low' | string;

export interface BreachedTicket {
    id: string;
    ticketNumber: string;
    subject: string;
    status: string;
    assignee: string;
    assigneeId?: string;
    priority: Priority;
    department: string;
    sla_status: 'breached' | 'at_risk';
    created_time: string | null;
    modified_time: string | null;
    due_date: string | null;
    hours_overdue: number;
    severity: Severity;
    zoho_url: string;
}

export interface SyncStatus {
    configured: boolean;
    last_sync_time: string | null;
    next_sync_time: string | null;
    sync_running: boolean;
    dept_counts: Record<string, number>;
    dept_errors: Record<string, string>;
}

export interface TicketsResponse {
    total: number;
    departments: Record<string, BreachedTicket[]>;
    sync_status: SyncStatus;
}

// ─── Sync API ─────────────────────────────────────────────────────────────
export const fetchSyncStatus = async (): Promise<SyncStatus> => {
    const r = await api.get('/api/sync/status');
    return r.data;
};

export const fetchTickets = async (dept?: string): Promise<TicketsResponse> => {
    const r = await api.get('/api/sync/tickets', {
        params: dept ? { dept } : undefined,
    });
    return r.data;
};

export const triggerSync = async (): Promise<{ status: string; message?: string }> => {
    const r = await api.post('/api/sync/trigger');
    return r.data;
};

export const fetchSyncLogs = async (): Promise<{ logs: Array<{ timestamp: string; level: string; message: string; dept?: string }> }> => {
    const r = await api.get('/api/sync/logs');
    return r.data;
};

export const fetchConfig = async () => {
    const r = await api.get('/api/sync/config');
    return r.data;
};

// ─── Action API ───────────────────────────────────────────────────────────
export const addComment = async (ticketId: string, content: string, isPublic = false) => {
    const r = await api.post('/api/actions/comment', { ticket_id: ticketId, content, is_public: isPublic });
    return r.data;
};

export const assignTicket = async (ticketId: string, agentId: string) => {
    const r = await api.post('/api/actions/assign', { ticket_id: ticketId, agent_id: agentId });
    return r.data;
};

export const escalateTicket = async (ticketId: string, note?: string) => {
    const r = await api.post('/api/actions/escalate', { ticket_id: ticketId, note });
    return r.data;
};
