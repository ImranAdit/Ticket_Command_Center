import React, { useState } from 'react';
import { ExternalLink, MessageSquare, UserPlus, AlertCircle, Loader2, Check } from 'lucide-react';
import { cn } from '../lib/utils';
import { type BreachedTicket, addComment, escalateTicket } from '../lib/api';

interface BreachTicketRowProps {
    ticket: BreachedTicket;
    onActionDone?: () => void;
}

export const BreachTicketRow: React.FC<BreachTicketRowProps> = ({ ticket, onActionDone }) => {
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [actionSuccess, setActionSuccess] = useState<string | null>(null);

    const handleAction = async (type: 'comment' | 'escalate', fn: () => Promise<any>) => {
        setActionLoading(type);
        try {
            await fn();
            setActionSuccess(type);
            setTimeout(() => {
                setActionSuccess(null);
                if (onActionDone) onActionDone();
            }, 2000);
        } catch (err) {
            console.error(`Action ${type} failed:`, err);
            alert(`Failed to ${type} ticket. API might be unreachable.`);
        } finally {
            setActionLoading(null);
        }
    };

    return (
        <div className={cn(
            "grid grid-cols-[3rem_8rem_1fr_7rem_7rem_8rem_7rem] gap-2 px-4 py-2.5 items-center transition-colors",
            "hover:bg-white/[0.03] border-b border-obsidian-border/30",
            ticket.severity === 'critical' && "severity-critical",
            ticket.severity === 'moderate' && "severity-moderate",
            ticket.severity === 'watch' && "severity-watch",
            ticket.severity === 'normal' && "severity-normal"
        )}>
            {/* Severity Icon */}
            <div className="flex justify-center">
                {ticket.severity === 'critical' ? (
                    <AlertCircle className="w-4 h-4 text-crimson-red shadow-[0_0_8px_rgba(239,68,68,0.4)]" />
                ) : ticket.severity === 'moderate' ? (
                    <AlertCircle className="w-4 h-4 text-amber-gold" />
                ) : (
                    <div className="w-1.5 h-1.5 rounded-full bg-text-faint" />
                )}
            </div>

            {/* Ticket ID */}
            <div className="font-mono text-[11px] font-bold text-text-muted hover:text-neon-blue transition-colors">
                <a href={ticket.zoho_url} target="_blank" rel="noreferrer" className="flex items-center gap-1">
                    {ticket.ticketNumber}
                    <ExternalLink className="w-2.5 h-2.5 opacity-40" />
                </a>
            </div>

            {/* Subject */}
            <div className="text-[12px] truncate pr-4 text-text-primary/90" title={ticket.subject}>
                {ticket.subject}
            </div>

            {/* Assignee */}
            <div className="text-[11px] text-text-muted truncate">
                {ticket.assignee}
            </div>

            {/* Priority */}
            <div>
                <span className={cn(
                    "px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider",
                    ticket.priority === 'High' ? "badge-high" : 
                    ticket.priority === 'Medium' ? "badge-medium" : "badge-low"
                )}>
                    {ticket.priority}
                </span>
            </div>

            {/* Overdue */}
            <div className="flex flex-col">
                <span className={cn(
                    "text-[11px] font-bold",
                    ticket.severity === 'critical' ? "text-crimson-red" : 
                    ticket.severity === 'moderate' ? "text-amber-gold" : "text-neon-blue"
                )}>
                    {ticket.hours_overdue} hrs
                </span>
                <span className="text-[9px] text-text-faint uppercase font-medium">Overdue</span>
            </div>

            {/* Quick Actions */}
            <div className="flex items-center gap-1.5">
                <button 
                    onClick={() => handleAction('comment', () => addComment(ticket.id, "Checking on this SLA breach.", false))}
                    disabled={!!actionLoading}
                    className="action-btn"
                    title="Add Internal Comment"
                >
                    {actionLoading === 'comment' ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                    ) : actionSuccess === 'comment' ? (
                        <Check className="w-3 h-3 text-green-ok" />
                    ) : (
                        <MessageSquare className="w-3 h-3" />
                    )}
                </button>

                <button 
                    onClick={() => handleAction('escalate', () => escalateTicket(ticket.id))}
                    disabled={!!actionLoading}
                    className="action-btn"
                    title="Escalate Ticket"
                >
                    {actionLoading === 'escalate' ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                    ) : actionSuccess === 'escalate' ? (
                        <Check className="w-3 h-3 text-green-ok" />
                    ) : (
                        <AlertCircle className="w-3 h-3" />
                    )}
                </button>

                <button className="action-btn" title="Reassign">
                   <UserPlus className="w-3 h-3" />
                </button>
            </div>
        </div>
    );
};
