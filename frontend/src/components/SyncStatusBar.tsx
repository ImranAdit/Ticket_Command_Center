import React, { useState } from 'react';
import { RefreshCw, CheckCircle, AlertTriangle, Clock, Wifi, WifiOff } from 'lucide-react';
import { cn } from '../lib/utils';
import { triggerSync, type SyncStatus } from '../lib/api';

interface SyncStatusBarProps {
    status: SyncStatus | null;
    onSyncComplete: () => void;
}

function timeAgo(iso: string | null): string {
    if (!iso) return 'Never';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    return `${Math.round(diff / 3600)}h ago`;
}

function timeUntil(iso: string | null): string {
    if (!iso) return '—';
    const diff = (new Date(iso).getTime() - Date.now()) / 1000;
    if (diff <= 0) return 'Now';
    if (diff < 60) return `${Math.round(diff)}s`;
    return `${Math.round(diff / 60)}m`;
}

export const SyncStatusBar: React.FC<SyncStatusBarProps> = ({ status, onSyncComplete }) => {
    const [syncing, setSyncing] = useState(false);
    const [syncMsg, setSyncMsg] = useState<string | null>(null);

    const handleManualSync = async () => {
        setSyncing(true);
        setSyncMsg(null);
        try {
            const res = await triggerSync();
            if (res.status === 'triggered') {
                setSyncMsg('Sync started…');
                // Poll for completion
                setTimeout(() => { onSyncComplete(); setSyncing(false); setSyncMsg(null); }, 6000);
            } else {
                setSyncMsg(res.message || res.status);
                setSyncing(false);
            }
        } catch {
            setSyncMsg('Sync failed — check backend');
            setSyncing(false);
        }
    };

    const isRunning = status?.sync_running || syncing;
    const hasErrors = status && Object.keys(status.dept_errors || {}).length > 0;
    const isConfigured = status?.configured ?? false;

    return (
        <div className={cn(
            "flex items-center justify-between px-6 py-2 border-b border-obsidian-border text-[11px] shrink-0",
            "bg-obsidian-bg/60 backdrop-blur-sm"
        )}>
            {/* Left: live status */}
            <div className="flex items-center gap-4">
                {isConfigured ? (
                    <div className="flex items-center gap-2 text-green-ok">
                        <span className="pulse-dot" />
                        <span className="font-medium tracking-wider uppercase">Live</span>
                    </div>
                ) : (
                    <div className="flex items-center gap-1.5 text-amber-gold">
                        <WifiOff className="w-3 h-3" />
                        <span className="font-medium">Not Connected — add Zoho credentials to .env</span>
                    </div>
                )}

                {isConfigured && (
                    <>
                        <div className="text-text-faint">|</div>
                        <div className="flex items-center gap-1 text-text-muted">
                            <Clock className="w-3 h-3" />
                            <span>Last sync: <span className="text-text-primary">{timeAgo(status?.last_sync_time ?? null)}</span></span>
                        </div>
                        <div className="flex items-center gap-1 text-text-muted">
                            <RefreshCw className="w-3 h-3" />
                            <span>Next: <span className="text-text-primary">{timeUntil(status?.next_sync_time ?? null)}</span></span>
                        </div>
                        {hasErrors && (
                            <div className="flex items-center gap-1 text-crimson-red">
                                <AlertTriangle className="w-3 h-3" />
                                <span>{Object.keys(status!.dept_errors).length} dept error(s)</span>
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* Right: Dept counts + manual sync */}
            <div className="flex items-center gap-4">
                {status && isConfigured && Object.entries(status.dept_counts).map(([dept, count]) => (
                    <div key={dept} className="flex items-center gap-1">
                        <span className="text-text-faint">{dept}:</span>
                        <span className={cn(
                            "font-bold tabular-nums",
                            count > 0 ? "text-crimson-red" : "text-green-ok"
                        )}>{count}</span>
                    </div>
                ))}

                {syncMsg && (
                    <span className="text-neon-blue animate-pulse">{syncMsg}</span>
                )}

                <button
                    onClick={handleManualSync}
                    disabled={isRunning || !isConfigured}
                    className={cn(
                        "flex items-center gap-1.5 px-3 py-1 rounded-lg border text-[10px] font-medium",
                        "border-obsidian-border2 text-text-muted bg-obsidian-card",
                        "hover:border-neon-blue/50 hover:text-neon-blue transition-all duration-200",
                        (isRunning || !isConfigured) && "opacity-40 cursor-not-allowed"
                    )}
                >
                    <RefreshCw className={cn("w-3 h-3", isRunning && "animate-spin")} />
                    {isRunning ? 'Syncing…' : 'Sync Now'}
                </button>
            </div>
        </div>
    );
};
