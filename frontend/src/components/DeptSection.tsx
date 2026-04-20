import React, { useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle, ShieldAlert } from 'lucide-react';
import { cn } from '../lib/utils';
import { type BreachedTicket } from '../lib/api';
import { BreachTicketRow } from './BreachTicketRow';

const DEPT_COLORS: Record<string, string> = {
    'VoIP':         'text-neon-blue border-neon-blue/30',
    'T1 Tech':      'text-purple-dev border-purple-dev/30',
    'T2 Core Tech': 'text-amber-gold border-amber-gold/30',
    'Adit Pay':     'text-green-ok border-green-ok/30',
};

const DEPT_ICONS: Record<string, string> = {
    'VoIP':         '📞',
    'T1 Tech':      '🔧',
    'T2 Core Tech': '⚙️',
    'Adit Pay':     '💳',
};

interface DeptSectionProps {
    name: string;
    tickets: BreachedTicket[];
    isLoading?: boolean;
    onActionDone?: () => void;
}

export const DeptSection: React.FC<DeptSectionProps> = ({
    name, tickets, isLoading = false, onActionDone
}) => {
    const [collapsed, setCollapsed] = useState(false);
    const colorClass = DEPT_COLORS[name] || 'text-text-primary border-obsidian-border2';
    const icon = DEPT_ICONS[name] || '📋';
    const criticalCount = tickets.filter(t => t.severity === 'critical').length;
    const moderateCount = tickets.filter(t => t.severity === 'moderate').length;

    return (
        <div className="rounded-xl border border-obsidian-border bg-obsidian-surface/60 overflow-hidden">
            {/* Section header */}
            <button
                className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-white/[0.02] transition-colors"
                onClick={() => setCollapsed(c => !c)}
            >
                <div className="flex items-center gap-3">
                    <span className="text-base">{icon}</span>
                    <span className={cn("font-bold tracking-wide text-[13px]", colorClass.split(' ')[0])}>
                        {name}
                    </span>

                    {/* Breach count badge */}
                    {tickets.length > 0 ? (
                        <div className="flex items-center gap-1.5">
                            <span className={cn(
                                "flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-full border",
                                "bg-crimson-red/10 text-crimson-red border-crimson-red/30"
                            )}>
                                <ShieldAlert className="w-3 h-3" />
                                {tickets.length} breach{tickets.length !== 1 ? 'es' : ''}
                            </span>
                            {criticalCount > 0 && (
                                <span className="text-[10px] px-1.5 py-0.5 bg-crimson-red/20 text-crimson-red rounded font-bold">
                                    {criticalCount} CRIT
                                </span>
                            )}
                            {moderateCount > 0 && (
                                <span className="text-[10px] px-1.5 py-0.5 bg-amber-gold/20 text-amber-gold rounded font-bold">
                                    {moderateCount} MOD
                                </span>
                            )}
                        </div>
                    ) : (
                        !isLoading && (
                            <span className="flex items-center gap-1 text-[11px] text-green-ok font-medium">
                                <CheckCircle className="w-3 h-3" /> All clear
                            </span>
                        )
                    )}
                </div>

                <div className="text-text-faint">
                    {collapsed
                        ? <ChevronRight className="w-4 h-4" />
                        : <ChevronDown className="w-4 h-4" />
                    }
                </div>
            </button>

            {/* Ticket list */}
            {!collapsed && (
                <div className="border-t border-obsidian-border/60">
                    {isLoading ? (
                        /* Skeleton rows */
                        <div className="flex flex-col gap-0">
                            {[...Array(3)].map((_, i) => (
                                <div key={i} className="flex gap-4 px-5 py-3 border-b border-obsidian-border/30">
                                    <div className="skeleton h-4 w-20 rounded" />
                                    <div className="skeleton h-4 flex-1 rounded" />
                                    <div className="skeleton h-4 w-16 rounded" />
                                    <div className="skeleton h-4 w-24 rounded" />
                                </div>
                            ))}
                        </div>
                    ) : tickets.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-10 text-text-faint gap-2">
                            <CheckCircle className="w-8 h-8 text-green-ok/40" />
                            <span className="text-sm">No SLA breaches with unactioned tickets</span>
                            <span className="text-xs">This department is operating within SLA</span>
                        </div>
                    ) : (
                        <div>
                            {/* Column headers */}
                            <div className="grid grid-cols-[3rem_8rem_1fr_7rem_7rem_8rem_7rem] gap-2 px-4 py-2
                                            bg-black/20 text-[9px] uppercase tracking-widest text-text-faint font-semibold border-b border-obsidian-border/40">
                                <span>Sev</span>
                                <span>Ticket ID</span>
                                <span>Subject</span>
                                <span>Assignee</span>
                                <span>Priority</span>
                                <span>Overdue</span>
                                <span>Actions</span>
                            </div>
                            {tickets.map(ticket => (
                                <BreachTicketRow
                                    key={ticket.id}
                                    ticket={ticket}
                                    onActionDone={onActionDone}
                                />
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};
