import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';

// Super-admin only: who else is signed in right now. The server returns 403 for
// everyone else, in which case this renders nothing.

interface ActiveUser {
    email: string;
    name?: string | null;
    picture?: string | null;
    role?: string;
    depts?: string[] | null;
    super?: boolean;
    seconds_ago: number;
    you: boolean;
}

const initials = (u: ActiveUser) =>
    (u.name || u.email).split(/[\s.@_-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join('');

const Avatar: React.FC<{ user: ActiveUser; size?: number; ring?: boolean }> = ({ user, size = 28, ring = true }) => {
    const [broken, setBroken] = useState(false);
    const style = { width: size, height: size };
    return (
        <span className="relative inline-flex shrink-0" style={style}>
            {user.picture && !broken ? (
                <img
                    src={user.picture}
                    alt={user.name || user.email}
                    referrerPolicy="no-referrer"
                    onError={() => setBroken(true)}
                    className={`rounded-full object-cover ${ring ? 'ring-2 ring-obsidian-surface' : ''}`}
                    style={style}
                />
            ) : (
                <span
                    className={`rounded-full flex items-center justify-center font-semibold text-white bg-gradient-to-br from-[#f7941d] to-[#2aa8e0] ${ring ? 'ring-2 ring-obsidian-surface' : ''}`}
                    style={{ ...style, fontSize: size * 0.38 }}
                >
                    {initials(user)}
                </span>
            )}
            <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-green-ok ring-2 ring-obsidian-surface" />
        </span>
    );
};

export const ActiveUsers: React.FC = () => {
    const [users, setUsers] = useState<ActiveUser[] | null>(null);
    const [open, setOpen] = useState(false);

    const load = useCallback(async () => {
        try {
            const r = await api.get('/api/auth/active');
            setUsers(r.data.users || []);
        } catch {
            setUsers(null); // not the super admin (403) or offline → hide
        }
    }, []);

    useEffect(() => {
        load();
        const t = setInterval(load, 30000);
        return () => clearInterval(t);
    }, [load]);

    if (!users) return null;

    const others = users.filter((u) => !u.you);
    const me = users.find((u) => u.you);
    const shown = others.slice(0, 5);
    const extra = others.length - shown.length;

    // nothing to show when nobody else is signed in
    if (others.length === 0) return null;

    return (
        <div className="relative" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
            <button
                onClick={() => setOpen((o) => !o)}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-obsidian-card border border-obsidian-border2 hover:border-neon-blue/40 transition-all"
                title="Who's online"
            >
                {others.length === 0 ? (
                    <span className="text-[11px] text-text-muted font-medium px-1">Only you online</span>
                ) : (
                    <>
                        <span className="flex -space-x-2">
                            {shown.map((u) => <Avatar key={u.email} user={u} />)}
                        </span>
                        {extra > 0 && <span className="text-[11px] text-text-muted font-semibold">+{extra}</span>}
                        <span className="text-[11px] text-text-muted font-medium">{others.length} online</span>
                    </>
                )}
            </button>

            {open && (
                <div className="absolute right-0 top-full pt-2 z-50">
                    <div className="w-72 rounded-xl border border-obsidian-border2 bg-obsidian-surface shadow-2xl p-2">
                        <div className="px-2 pt-1 pb-2 text-[10px] uppercase tracking-widest text-text-muted font-semibold">
                            Signed in now
                        </div>
                        {[...others, ...(me ? [me] : [])].map((u) => (
                            <div key={u.email} className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-white/[0.03]">
                                <Avatar user={u} size={32} ring={false} />
                                <div className="min-w-0 flex-1">
                                    <div className="text-[12px] font-semibold text-text-primary truncate">
                                        {u.name || u.email.split('@')[0]}{u.you && <span className="text-text-muted font-normal"> (you)</span>}
                                    </div>
                                    <div className="text-[10px] text-text-faint truncate">
                                        {u.super ? 'Super Admin' : u.role === 'admin' ? 'Full access' : (u.depts || []).join(' · ')}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};
