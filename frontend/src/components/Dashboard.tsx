import React, { useState, useCallback, useMemo } from 'react';
import { useDropzone } from 'react-dropzone';
import { LogOut, UploadCloud, Hexagon, Activity, Clock, AlertTriangle } from 'lucide-react';
import { cn } from '../lib/utils';
import { classifyTickets, TicketData, MetricResult } from '../lib/api';

interface DashboardProps {
    userEmail: string;
    onLogout: () => void;
}

// Minimal CSV parser since xlsx logic requires a heavy library
// We assume CSV dropping for simplicity unless specified
const parseCSV = (csvText: string): any[] => {
    const lines = csvText.trim().split('\\n');
    if (lines.length < 2) return [];
    
    // Parse headers handling quotes
    const parseLine = (line: string) => {
        const row = [];
        let curr = '';
        let inQuotes = false;
        for (let i = 0; i < line.length; i++) {
            if (line[i] === '"') inQuotes = !inQuotes;
            else if (line[i] === ',' && !inQuotes) {
                row.push(curr.trim());
                curr = '';
            } else {
                curr += line[i];
            }
        }
        row.push(curr.trim());
        return row;
    };

    const headers = parseLine(lines[0]).map(h => h.toLowerCase());
    return lines.slice(1).map(line => {
        const values = parseLine(line);
        const obj: any = {};
        headers.forEach((h, i) => obj[h] = values[i] || '');
        return obj;
    });
};

const mapHeaders = (rows: any[]): TicketData[] => {
    return rows.map((r, i) => {
        const getVal = (keys: string[]) => {
            for (const k of keys) {
                const found = Object.keys(r).find(key => key.includes(k));
                if (found) return r[found];
            }
            return '';
        };

        const id = getVal(['id', 'ticket #']);
        const agent = getVal(['agent', 'owner']);
        const subject = getVal(['subject', 'title']);
        const status = getVal(['status']);
        const team = getVal(['team', 'dept']);
        const createdAt = getVal(['created time', 'date created', 'open date']);
        const modifiedAt = getVal(['modified time', 'agent responded', 'last reply']);

        // Default missing createdAt to current time for safe parsing in backend
        return {
            id: id || `TKT-${i}`,
            agent: agent || 'Unassigned',
            subject: subject || 'No Subject',
            status: status || 'Open',
            team: team || 'General',
            created_at: createdAt || new Date().toISOString(),
            modified_at: modifiedAt || undefined,
        };
    });
};

export const Dashboard: React.FC<DashboardProps> = ({ userEmail, onLogout }) => {
    const [activeTab, setActiveTab] = useState('All');
    const tabs = ['VoIP', 'T1 Tech', 'T2 Core Tech', 'Adit Pay', 'All'];
    
    const [tickets, setTickets] = useState<(TicketData & { metrics?: MetricResult['metrics'] })[]>([]);
    const [loading, setLoading] = useState(false);

    const onDrop = useCallback(async (acceptedFiles: File[]) => {
        if (!acceptedFiles.length) return;
        const file = acceptedFiles[0];
        setLoading(true);

        try {
            const text = await file.text();
            let parsedRows = [];
            if (file.name.endsWith('.csv')) {
                parsedRows = parseCSV(text);
            } else {
                alert("For this demo, please upload a .csv file exported from Zoho.");
                setLoading(false);
                return;
            }

            const mapped = mapHeaders(parsedRows);
            // Call FastAPI backend to calculate Idle Time Metrics!
            const classified = await classifyTickets(mapped);
            
            // Join data
            const finalData = mapped.map(t => {
                const match = classified.find(c => String(c.id) === String(t.id));
                return { ...t, metrics: match?.metrics };
            });

            setTickets(finalData);

        } catch (err) {
            console.error("Error processing file", err);
            alert("Error processing file. Backend might be down.");
        } finally {
            setLoading(false);
        }
    }, []);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({ 
        onDrop,
        accept: { 'text/csv': ['.csv'] }
    });

    const filteredTickets = useMemo(() => {
        return tickets.filter(t => {
            if (activeTab === 'All') return true;
            return t.team?.toLowerCase().includes(activeTab.replace(' Tech', '').toLowerCase());
        });
    }, [tickets, activeTab]);

    const stats = useMemo(() => {
        let flash = 0, stagnant = 0, devOverdue = 0;
        tickets.forEach(t => {
            if (t.metrics?.alert_class === 'flash') flash++;
            if (t.metrics?.alert_class === '24h+' || t.metrics?.alert_class === '48h+' || t.metrics?.alert_class === '72h+') stagnant++;
            if (t.metrics?.alert_class === 'dev_overdue') devOverdue++;
        });
        return { flash, stagnant, devOverdue };
    }, [tickets]);

    const leaderboard = useMemo(() => {
        const counts: Record<string, number> = {};
        tickets.forEach(t => {
            if (t.status.toLowerCase() !== 'closed' && t.agent) {
                counts[t.agent] = (counts[t.agent] || 0) + 1;
            }
        });
        return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
    }, [tickets]);

    const getRowClass = (alertClass?: string) => {
        switch (alertClass) {
            case 'flash': return 'border-l-4 border-l-green-ok';
            case '24h+': return 'border-l-4 border-l-neon-blue';
            case '48h+': return 'border-l-4 border-l-amber-gold';
            case '72h+': return 'border-l-4 border-l-crimson-red';
            case 'dev_overdue': return 'border-l-4 border-l-purple-dev';
            default: return 'border-l-4 border-l-transparent';
        }
    };

    return (
        <div className="flex flex-col h-screen w-full bg-obsidian-bg overflow-hidden text-text-primary">
            {/* Topbar Nav */}
            <div className="flex items-center justify-between px-6 py-3 bg-obsidian-surface border-b border-obsidian-border shrink-0">
                <div className="flex items-center gap-2 font-bold tracking-widest text-[14px]">
                    ADIT <span className="text-neon-blue">◈</span> TCC
                </div>

                <div className="flex bg-obsidian-bg p-1 rounded-xl border border-obsidian-border mx-4">
                    {tabs.map(tab => (
                        <button 
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={cn(
                                "px-4 py-1.5 rounded-lg text-xs font-medium transition-all duration-200",
                                activeTab === tab 
                                    ? "bg-neon-blue text-black font-bold shadow-[0_0_10px_rgba(0,180,255,0.3)]" 
                                    : "text-text-muted hover:text-text-primary hover:bg-obsidian-card"
                            )}
                        >
                            {tab}
                        </button>
                    ))}
                </div>

                <div className="flex items-center gap-4">
                    <div className="text-xs text-text-muted bg-obsidian-card border border-obsidian-border2 px-3 py-1 rounded-full">
                        {userEmail}
                    </div>
                    <button 
                        onClick={onLogout}
                        className="flex items-center gap-1.5 text-xs text-text-muted hover:text-crimson-red border border-transparent hover:border-crimson-red/30 px-2 py-1 rounded transition-colors"
                    >
                        <LogOut className="w-3.5 h-3.5" /> Sign Out
                    </button>
                </div>
            </div>

            {/* Hero Metrics Pulse Cards */}
            <div className="grid grid-cols-3 gap-4 px-6 py-4 shrink-0">
                <div className="glass-card p-5 relative overflow-hidden group border-t-2 border-t-neon-blue">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity"><Activity className="w-16 h-16 text-neon-blue" /></div>
                    <div className="text-[10px] tracking-widest uppercase text-text-muted mb-2">Critical Today (4h Flash)</div>
                    <div className="text-4xl font-bold text-neon-blue text-glow-neon">{stats.flash}</div>
                    <div className="text-xs text-text-faint mt-1">Created today, no action within 4 biz hrs</div>
                </div>
                
                <div className="glass-card p-5 relative overflow-hidden group border-t-2 border-t-amber-gold">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity"><Clock className="w-16 h-16 text-amber-gold" /></div>
                    <div className="text-[10px] tracking-widest uppercase text-text-muted mb-2">Stagnant (&gt;24h Idle)</div>
                    <div className="text-4xl font-bold text-amber-gold">{stats.stagnant}</div>
                    <div className="text-xs text-text-faint mt-1">Unactioned beyond 24 business hours</div>
                </div>
                
                <div className="glass-card p-5 relative overflow-hidden group border-t-2 border-t-crimson-red">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity"><AlertTriangle className="w-16 h-16 text-crimson-red" /></div>
                    <div className="text-[10px] tracking-widest uppercase text-text-muted mb-2">Overdue Dev (&gt;3d Pending)</div>
                    <div className="text-4xl font-bold text-crimson-red">{stats.devOverdue}</div>
                    <div className="text-xs text-text-faint mt-1">Pending Development &gt; 3 business days</div>
                </div>
            </div>

            {/* Main Content Area */}
            <div className="flex flex-1 overflow-hidden px-6 pb-6 gap-6">
                
                {/* Action Grid Panel */}
                <div className="flex-1 flex flex-col bg-obsidian-surface border border-obsidian-border rounded-xl overflow-hidden glassmorphism">
                    <div className="px-5 py-3 border-b border-obsidian-border flex items-center justify-between bg-black/20">
                        <div className="text-xs tracking-widest uppercase text-text-muted font-bold">Action Grid</div>
                    </div>

                    {tickets.length === 0 ? (
                        <div className="flex-1 flex flex-col items-center justify-center p-8">
                            <div 
                                {...getRootProps()} 
                                className={cn(
                                    "w-full max-w-md border-2 border-dashed rounded-xl p-10 flex flex-col items-center justify-center cursor-pointer transition-colors duration-200",
                                    isDragActive ? "border-neon-blue bg-neon-blue-glow" : "border-obsidian-border2 hover:border-text-muted hover:bg-obsidian-card"
                                )}
                            >
                                <input {...getInputProps()} />
                                <UploadCloud className="w-12 h-12 text-text-faint mb-4" />
                                <div className="text-sm text-text-muted text-center">
                                    <b className="text-neon-blue">Drag & drop</b> your CSV ticket export here
                                </div>
                                <div className="text-xs text-text-faint mt-2">Supports Data mapped to VoIP Summary fields</div>
                                {loading && <div className="mt-4 text-xs text-neon-blue animate-pulse">Calculating Business Logic...</div>}
                            </div>
                        </div>
                    ) : (
                        <div className="flex-1 overflow-auto">
                            <table className="w-full text-left border-collapse min-w-[800px]">
                                <thead className="bg-obsidian-bg sticky top-0 z-10 text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                                    <tr>
                                        <th className="p-3 border-b border-obsidian-border">Ticket ID</th>
                                        <th className="p-3 border-b border-obsidian-border">Agent</th>
                                        <th className="p-3 border-b border-obsidian-border">Subject</th>
                                        <th className="p-3 border-b border-obsidian-border">Status</th>
                                        <th className="p-3 border-b border-obsidian-border">Idle Time / Class</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filteredTickets.map((t, idx) => (
                                        <tr key={idx} className={cn(
                                            "border-b border-obsidian-border/50 hover:bg-white/5 transition-colors text-xs",
                                            getRowClass(t.metrics?.alert_class)
                                        )}>
                                            <td className="p-3 font-mono font-medium">
                                                <a href={`https://desk.zoho.com/support/adit/ShowHomePage.do#Cases/dv/${t.id}`} target="_blank" rel="noreferrer" className="text-neon-blue hover:underline">
                                                    {t.id}
                                                </a>
                                            </td>
                                            <td className="p-3">{t.agent}</td>
                                            <td className="p-3 max-w-[250px] truncate" title={t.subject}>{t.subject}</td>
                                            <td className="p-3">
                                                <span className="bg-obsidian-card border border-obsidian-border2 px-2 py-0.5 rounded text-[10px] uppercase font-bold text-text-muted">
                                                    {t.status}
                                                </span>
                                            </td>
                                            <td className="p-3 font-mono text-[11px] flex flex-col gap-0.5">
                                                {t.metrics ? (
                                                    <>
                                                        <span className={t.metrics.alert_class !== 'normal' ? 'font-bold' : ''}>
                                                            {t.metrics.biz_hours_idle} biz hrs
                                                        </span>
                                                        <span className="text-[9px] text-text-faint uppercase">{t.metrics.alert_class.replace('_', ' ')}</span>
                                                    </>
                                                ) : 'Evaluating...'}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* Sidebar - Leaderboard */}
                <div className="w-[280px] shrink-0 flex flex-col gap-6">
                    <div className="flex-1 bg-obsidian-surface border border-obsidian-border rounded-xl flex flex-col overflow-hidden glassmorphism">
                        <div className="px-5 py-3 border-b border-obsidian-border bg-black/20">
                            <div className="text-xs tracking-widest uppercase text-text-muted font-bold">Leaderboard</div>
                            <div className="text-[10px] text-text-faint mt-0.5">Ranked by unactioned count</div>
                        </div>
                        <div className="flex-1 overflow-auto p-2">
                            {leaderboard.length === 0 ? (
                                <div className="text-center p-6 text-xs text-text-faint">No agent data available</div>
                            ) : (
                                leaderboard.map(([agent, count], i) => (
                                    <div key={agent} className="flex items-center gap-3 p-2 border-b border-obsidian-border/30 last:border-0 hover:bg-obsidian-card rounded transition-colors">
                                        <div className="w-5 text-center text-xs font-mono text-text-faint">{i + 1}</div>
                                        <div className="flex-1 truncate text-xs text-text-primary">{agent}</div>
                                        <div className="text-xs font-bold text-amber-gold">{count}</div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                </div>

            </div>
        </div>
    );
};
