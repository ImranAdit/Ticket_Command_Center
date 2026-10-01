import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ExternalLink, Inbox, RefreshCw, AlertCircle } from 'lucide-react';
import { cn } from '../lib/utils';
import { api } from '../lib/api';

// "T2 CS - Open Unassigned" Zoho view, shown on demand (owner + QUEUE_VIEWERS only).

export interface QueueTicket {
    id: string;
    ticketNumber: string;
    subject: string;
    deal_name?: string | null;
    priority: string;
    created_by?: string | null;
    created_time?: string | null;
    last_note_time?: string | null;
    zoho_url: string;
}

interface QueueResponse {
    view?: string;
    count?: number;
    tickets?: QueueTicket[];
    generated_at?: string;
    warning?: string;
    error?: string;
}

export const fetchUnassignedQueue = async (refresh = false): Promise<QueueResponse> =>
    (await api.get('/api/queue/t2cs-unassigned', { params: refresh ? { refresh: 1 } : undefined })).data;

const fmtCT = (iso: string, withYear = false) =>
    new Date(iso).toLocaleString('en-US', {
        timeZone: 'America/Chicago', month: 'short', day: 'numeric',
        ...(withYear ? { year: 'numeric' } : {}), hour: 'numeric', minute: '2-digit',
    });

const ageLabel = (iso: string) => {
    const h = (Date.now() - new Date(iso).getTime()) / 3600000;
    if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`;
    if (h < 48) return `${Math.round(h)}h ago`;
    return `${Math.round(h / 24)}d ago`;
};

const GRID = 'grid grid-cols-[7rem_13rem_1fr_7rem_10rem_9rem_9rem] gap-2';

export const UnassignedQueue: React.FC<{ search: string; onCount?: (n: number) => void }> = ({ search, onCount }) => {
    const [data, setData] = useState<QueueResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async (refresh = false) => {
        refresh ? setRefreshing(true) : setLoading(true);
        try {
            const r = await fetchUnassignedQueue(refresh);
            setData(r);
            setError(null);
            onCount?.(r.count ?? r.tickets?.length ?? 0);
        } catch (e: any) {
            setError(e?.response?.data?.error || e?.response?.data?.detail || 'Could not load the queue from Zoho');
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [onCount]);

    useEffect(() => {
        load();
        const t = setInterval(() => load(), 60000);
        return () => clearInterval(t);
    }, [load]);

    const rows = useMemo(() => {
        const q = search.trim().toLowerCase();
        const list = data?.tickets || [];
        if (!q) return list;
        return list.filter((t) =>
            [t.ticketNumber, t.subject, t.deal_name, t.created_by, t.priority]
                .some((v) => (v || '').toLowerCase().includes(q)));
    }, [data, search]);

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
                <h2 className="text-[11px] uppercase tracking-[3px] font-black text-text-muted flex items-center gap-2">
                    <Inbox className="w-3.5 h-3.5" /> Queue View
                </h2>
                <button
                    onClick={() => load(true)}
                    disabled={refreshing || loading}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg border text-[10px] font-medium border-obsidian-border2 text-text-muted bg-obsidian-card hover:border-neon-blue/50 hover:text-neon-blue transition-all disabled:opacity-40"
                >
                    <RefreshCw className={cn('w-3 h-3', refreshing && 'animate-spin')} /> Refresh
                </button>
            </div>

            <div className="rounded-xl border border-obsidian-border bg-obsidian-surface/60 overflow-hidden">
                <div className="w-full flex items-center justify-between px-5 py-3.5">
                    <div className="flex items-center gap-3">
                        <span className="text-base">📥</span>
                        <span className="font-bold tracking-wide text-[13px] text-neon-blue">
                            {data?.view || 'T2 CS - Open Unassigned'}
                        </span>
                        {!loading && !error && (
                            <span className="flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-full border bg-neon-blue/10 text-neon-blue border-neon-blue/30">
                                {data?.count ?? 0} unassigned
                            </span>
                        )}
                    </div>
                    {data?.generated_at && (
                        <span className="text-[10px] text-text-faint">
                            Updated {fmtCT(data.generated_at)} CT{data.warning ? ' · showing last good copy' : ''}
                        </span>
                    )}
                </div>

                <div className="border-t border-obsidian-border/60">
                    {loading ? (
                        <div className="flex flex-col">
                            {[...Array(4)].map((_, i) => (
                                <div key={i} className="flex gap-4 px-5 py-3 border-b border-obsidian-border/30">
                                    <div className="skeleton h-4 w-20 rounded" />
                                    <div className="skeleton h-4 w-40 rounded" />
                                    <div className="skeleton h-4 flex-1 rounded" />
                                    <div className="skeleton h-4 w-24 rounded" />
                                </div>
                            ))}
                        </div>
                    ) : error ? (
                        <div className="flex flex-col items-center justify-center py-10 text-crimson-red gap-2 px-6 text-center">
                            <AlertCircle className="w-8 h-8 text-crimson-red/60" />
                            <span className="text-sm">Could not load this queue from Zoho</span>
                            <span className="text-xs text-text-faint break-all">{error}</span>
                        </div>
                    ) : rows.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-10 text-text-faint gap-2">
                            <Inbox className="w-8 h-8 text-green-ok/40" />
                            <span className="text-sm">{search ? 'No tickets match your search' : 'No unassigned tickets in this queue'}</span>
                        </div>
                    ) : (
                        <div>
                            <div className={cn(GRID, 'px-4 py-2 bg-black/20 text-[10px] uppercase tracking-widest text-[#A3B1CC] font-semibold border-b border-obsidian-border/40')}>
                                <span>Ticket ID</span>
                                <span>Deal Name</span>
                                <span>Subject</span>
                                <span>Priority</span>
                                <span>Created By</span>
                                <span>Created (CT)</span>
                                <span>Last Note (CT)</span>
                            </div>
                            {rows.map((t) => (
                                <div key={t.id} className={cn(GRID, 'px-4 py-2.5 items-center transition-colors hover:bg-white/[0.03] border-b border-obsidian-border/30 border-l-[3px] border-l-neon-blue/60')}>
                                    <div className="font-mono text-[11px] font-bold text-text-muted hover:text-neon-blue transition-colors">
                                        <a href={t.zoho_url} target="_blank" rel="noreferrer" className="flex items-center gap-1">
                                            {t.ticketNumber}
                                            <ExternalLink className="w-2.5 h-2.5 opacity-40" />
                                        </a>
                                    </div>
                                    <div className="text-[11px] text-text-primary/90 truncate pr-2" title={t.deal_name || ''}>
                                        {t.deal_name || <span className="text-text-faint">—</span>}
                                    </div>
                                    <div className="text-[12px] truncate text-text-primary/90 pr-4" title={t.subject}>
                                        {t.subject}
                                    </div>
                                    <div>
                                        <span className={cn(
                                            'px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider',
                                            t.priority === 'High' ? 'badge-high' :
                                            t.priority === 'Medium' ? 'badge-medium' : 'badge-low'
                                        )}>
                                            {t.priority}
                                        </span>
                                    </div>
                                    <div className="text-[11px] text-text-muted truncate" title={t.created_by || ''}>
                                        {t.created_by || '—'}
                                    </div>
                                    {t.created_time ? (
                                        <div className="flex flex-col" title={`${fmtCT(t.created_time, true)} CT`}>
                                            <span className="text-[11px] text-text-primary/90 whitespace-nowrap">{fmtCT(t.created_time)}</span>
                                            <span className="text-[9px] text-text-faint uppercase font-medium">{ageLabel(t.created_time)}</span>
                                        </div>
                                    ) : <div className="text-[11px] text-text-faint">—</div>}
                                    {t.last_note_time ? (
                                        <div className="flex flex-col" title={`Last note: ${fmtCT(t.last_note_time, true)} CT`}>
                                            <span className="text-[11px] text-text-primary/90 whitespace-nowrap">{fmtCT(t.last_note_time)}</span>
                                            <span className="text-[9px] text-text-faint uppercase font-medium">{ageLabel(t.last_note_time)}</span>
                                        </div>
                                    ) : (
                                        <div className="flex flex-col">
                                            <span className="text-[11px] text-text-faint">—</span>
                                            <span className="text-[9px] text-text-faint uppercase font-medium">No notes</span>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
