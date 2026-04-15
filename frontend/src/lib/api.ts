import axios from 'axios';

export const BACKEND_URL = 'http://localhost:8000';

export const api = axios.create({
    baseURL: BACKEND_URL,
    headers: {
        'Content-Type': 'application/json'
    }
});

// We can define the shape of logic/classify endpoint
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
    // Backend expects an array of tickets
    const response = await api.post('/api/logic/classify', { tickets });
    return response.data.results;
};
