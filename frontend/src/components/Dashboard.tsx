import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { LogOut, Activity, Clock, ShieldAlert, LayoutDashboard, Search, Filter } from 'lucide-react';
import { fetchSyncStatus, fetchTickets, type BreachedTicket, type SyncStatus } from '../lib/api';
import { SyncStatusBar } from './SyncStatusBar';
import { DeptSection } from './DeptSection';

interface DashboardProps {
    userEmail: string;
    onLogout: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ userEmail, onLogout }) => {
    const [searchQuery, setSearchQuery] = useState('');
    const [status, setStatus] = useState<SyncStatus | null>(null);
    const [ticketsByDept, setTicketsByDept] = useState<Record<string, BreachedTicket[]>>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const loadData = useCallback(async (isInitial = false) => {
        if (isInitial) setLoading(true);
        try {
            const [statusRes, ticketsRes] = await Promise.all([
                fetchSyncStatus(),
                fetchTickets()
            ]);
            setStatus(statusRes);
            setTicketsByDept(ticketsRes.departments);
            setError(null);
        } catch (err) {
            console.error("Failed to load dashboard data:", err);
            setError("Backend unreachable. Ensure FastAPI server is running on port 8000.");
        } finally {
            if (isInitial) setLoading(false);
        }
    }, []);

    // Initial load + Polling
    useEffect(() => {
        loadData(true);
        const interval = setInterval(() => loadData(false), 60000); // 60s poll
        return () => clearInterval(interval);
    }, [loadData]);

    const stats = useMemo(() => {
        const allTickets = Object.values(ticketsByDept).flat();
        const critical = allTickets.filter(t => t.severity === 'critical').length;
        const deptsImpacted = Object.entries(ticketsByDept).filter(([_, t]) => t.length > 0).length;
        
        return {
            total: allTickets.length,
            critical,
            deptsImpacted
        };
    }, [ticketsByDept]);

    const filteredDepts = useMemo(() => {
        const query = searchQuery.toLowerCase();
        const results: Record<string, BreachedTicket[]> = {};
        
        Object.entries(ticketsByDept).forEach(([dept, tickets]) => {
            const filtered = tickets.filter(t => 
                t.ticketNumber.toLowerCase().includes(query) || 
                t.subject.toLowerCase().includes(query) ||
                t.assignee.toLowerCase().includes(query)
            );
            if (filtered.length > 0 || query === '') {
                results[dept] = filtered;
            }
        });
        return results;
    }, [ticketsByDept, searchQuery]);

    return (
        <div className="flex flex-col h-screen w-full bg-obsidian-bg overflow-hidden text-text-primary">
            {/* Topbar Nav */}
            <header className="flex items-center justify-between px-6 py-3 bg-obsidian-surface border-b border-obsidian-border shrink-0 z-20">
                <div className="flex items-center gap-3">
                    <img 
                        src="https://adit.com/storage/settings/logo.png" 
                        alt="Adit" 
                        className="h-[24px] object-contain"
                    />
                    <div className="flex items-center gap-2">
                        <span className="text-text-muted font-light px-2">|</span>
                        <div className="flex items-center gap-2 text-[11px] tracking-[3px] uppercase font-bold">
                            TCC <span className="text-[10px] text-neon-blue font-mono px-1.5 py-0.5 bg-neon-blue/10 border border-neon-blue/20 rounded">v2.0</span>
                        </div>
                    </div>
                </div>

                {/* Global Search */}
                <div className="flex-1 max-w-md px-8">
                    <div className="relative group">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-faint group-focus-within:text-neon-blue transition-colors" />
                        <input 
                            type="text"
                            placeholder="Search by ticket #, subject, or agent..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full bg-obsidian-bg border border-obsidian-border2 rounded-lg py-2 pl-10 pr-4 text-xs focus:outline-none focus:border-neon-blue/50 focus:ring-1 focus:ring-neon-blue/20 transition-all placeholder:text-text-faint"
                        />
                    </div>
                </div>

                <div className="flex items-center gap-6">
                    <div className="flex flex-col items-end">
                        <span className="text-[10px] text-text-muted uppercase tracking-wider font-medium">Logged in as</span>
                        <span className="text-xs font-bold text-text-primary">{userEmail}</span>
                    </div>
                    <button 
                        onClick={onLogout}
                        className="p-2.5 rounded-xl bg-obsidian-card border border-obsidian-border2 text-text-muted hover:text-crimson-red hover:border-crimson-red/30 transition-all group"
                    >
                        <LogOut className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
                    </button>
                </div>
            </header>

            {/* Live Sync Status Strip */}
            <SyncStatusBar status={status} onSyncComplete={() => loadData(false)} />

            {/* Main Content Scrollable Area */}
            <main className="flex-1 overflow-y-auto custom-scrollbar bg-obsidian-bg relative">
                {/* Visual Background Decors */}
                <div className="absolute top-0 left-1/4 w-[500px] h-[300px] bg-neon-blue/5 blur-[120px] pointer-events-none rounded-full" />
                <div className="absolute bottom-0 right-1/4 w-[400px] h-[300px] bg-purple-dev/5 blur-[120px] pointer-events-none rounded-full" />

                <div className="max-w-[1400px] mx-auto p-6 flex flex-col gap-6 relative z-10">
                    
                    {/* Hero Metric Tiles */}
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                        <div className="glass-card p-5 group flex flex-col gap-3 hover:border-neon-blue/30 transition-all border-t-2 border-t-neon-blue">
                             <div className="flex items-center justify-between">
                                <span className="text-[10px] uppercase tracking-[2px] font-bold text-text-muted">Total Breaches</span>
                                <Activity className="w-4 h-4 text-neon-blue group-hover:scale-110 transition-transform" />
                             </div>
                             <div className="text-3xl font-bold tracking-tight text-glow-neon">
                                {loading ? "..." : stats.total}
                             </div>
                             <div className="text-[10px] text-text-faint font-medium">Auto-synced from Zoho Desk</div>
                        </div>

                        <div className="glass-card p-5 group flex flex-col gap-3 hover:border-crimson-red/30 transition-all border-t-2 border-t-crimson-red">
                             <div className="flex items-center justify-between">
                                <span className="text-[10px] uppercase tracking-[2px] font-bold text-text-muted">Critical Status</span>
                                <ShieldAlert className="w-4 h-4 text-crimson-red group-hover:scale-110 transition-transform pulse" />
                             </div>
                             <div className="text-3xl font-bold tracking-tight text-crimson-red">
                                {loading ? "..." : stats.critical}
                             </div>
                             <div className="text-[10px] text-text-faint font-medium">&gt; 72 hours overdue without action</div>
                        </div>

                        <div className="glass-card p-5 group flex flex-col gap-3 hover:border-purple-dev/30 transition-all border-t-2 border-t-purple-dev">
                             <div className="flex items-center justify-between">
                                <span className="text-[10px] uppercase tracking-[2px] font-bold text-text-muted">Depts Impacted</span>
                                <LayoutDashboard className="w-4 h-4 text-purple-dev group-hover:scale-110 transition-transform" />
                             </div>
                             <div className="text-3xl font-bold tracking-tight">
                                {loading ? "..." : stats.deptsImpacted}
                             </div>
                             <div className="text-[10px] text-text-faint font-medium">Departments with active breaches</div>
                        </div>

                        <div className="glass-card p-5 group flex flex-col gap-3 hover:border-amber-gold/30 transition-all border-t-2 border-t-amber-gold">
                             <div className="flex items-center justify-between">
                                <span className="text-[10px] uppercase tracking-[2px] font-bold text-text-muted">Next Sync Window</span>
                                <Clock className="w-4 h-4 text-amber-gold group-hover:scale-110 transition-transform" />
                             </div>
                             <div className="text-3xl font-bold tracking-tight text-amber-gold">
                                {loading ? "..." : (status?.sync_running ? "RUNNING" : "15m")}
                             </div>
                             <div className="text-[10px] text-text-faint font-medium">Automated poll frequency</div>
                        </div>
                    </div>

                    {/* Department Sections */}
                    <div className="flex flex-col gap-6 mt-2">
                        <div className="flex items-center justify-between">
                            <h2 className="text-[11px] uppercase tracking-[3px] font-black text-text-muted flex items-center gap-2">
                                <Filter className="w-3.5 h-3.5" /> Departmental Monitoring
                            </h2>
                            {error && (
                                <div className="text-[10px] text-crimson-red bg-crimson-red/10 border border-crimson-red/20 px-3 py-1 rounded-full font-bold animate-pulse">
                                    {error}
                                </div>
                            )}
                        </div>

                        <div className="grid grid-cols-1 gap-6">
                            {loading ? (
                                [...Array(4)].map((_, i) => (
                                    <div key={i} className="h-[200px] glass-card skeleton" />
                                ))
                            ) : Object.keys(filteredDepts).length === 0 ? (
                                <div className="glass-card p-20 flex flex-col items-center justify-center gap-4 text-center">
                                    <div className="w-16 h-16 rounded-full bg-green-ok/10 flex items-center justify-center border border-green-ok/20">
                                        <Activity className="w-8 h-8 text-green-ok" />
                                    </div>
                                    <div>
                                        <div className="text-lg font-bold">All Quiet on the Front</div>
                                        <p className="text-sm text-text-muted max-w-sm mt-1">
                                            No SLA breaches found matching your current filters. Great job!
                                        </p>
                                    </div>
                                </div>
                            ) : (
                                Object.entries(filteredDepts).map(([dept, tickets]) => (
                                    <DeptSection 
                                        key={dept}
                                        name={dept}
                                        tickets={tickets}
                                        isLoading={loading}
                                        onActionDone={() => loadData(false)}
                                    />
                                ))
                            )}
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
};
