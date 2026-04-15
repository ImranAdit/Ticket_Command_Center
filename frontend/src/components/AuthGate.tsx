import React, { useState } from 'react';
import { cn } from '../lib/utils';
import { Hexagon, Lock } from 'lucide-react';

interface AuthGateProps {
    onLogin: (email: string) => void;
}

export const AuthGate: React.FC<AuthGateProps> = ({ onLogin }) => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        
        if (!email.toLowerCase().endsWith('@adit.com')) {
            setError('Access denied — must use an @adit.com email address.');
            return;
        }
        
        if (!password) {
            setError('Password is required.');
            return;
        }
        
        // Success
        setError('');
        onLogin(email);
    };

    return (
        <div className="flex bg-obsidian-bg items-center justify-center min-h-screen relative overflow-hidden">
            <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(0, 180, 255, 0.12) 0%, transparent 70%)' }}></div>
            
            <div className="glass-card p-10 w-[420px] max-w-full relative z-10">
                <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[60%] h-[1px] bg-gradient-to-r from-transparent via-neon-blue to-transparent"></div>
                
                <div className="text-[22px] font-bold text-text-primary tracking-[2px] text-center mb-1 flex items-center justify-center gap-2">
                    ADIT <Hexagon className="w-5 h-5 text-neon-blue fill-neon-blue" />
                </div>
                <div className="text-[11px] text-text-muted text-center tracking-[3px] uppercase mb-8">
                    Ticket Command Center
                </div>

                <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                    <div>
                        <label className="text-[11px] text-text-muted tracking-[1px] uppercase mb-1.5 block">Email Address</label>
                        <input 
                            value={email}
                            onChange={e => setEmail(e.target.value)}
                            type="email" 
                            className="w-full bg-obsidian-surface border border-obsidian-border2 rounded-lg py-2.5 px-3.5 text-[13px] text-text-primary outline-none focus:border-neon-blue transition-colors"
                            placeholder="you@adit.com"
                        />
                    </div>
                    
                    <div>
                        <label className="text-[11px] text-text-muted tracking-[1px] uppercase mb-1.5 block">Password</label>
                        <input 
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            type="password" 
                            className="w-full bg-obsidian-surface border border-obsidian-border2 rounded-lg py-2.5 px-3.5 text-[13px] text-text-primary outline-none focus:border-neon-blue transition-colors"
                            placeholder="••••••••"
                        />
                    </div>

                    <button 
                        type="submit"
                        className="w-full mt-5 py-[11px] bg-neon-blue border-none rounded-lg text-black text-[13px] font-bold cursor-pointer tracking-[1px] uppercase transition-opacity hover:opacity-85"
                    >
                        Access Command Center
                    </button>
                    
                    {error && (
                        <div className="text-crimson-red text-xs mt-2.5 text-center min-h-[18px]">
                            {error}
                        </div>
                    )}

                    <div className="text-[11px] text-text-faint flex items-center justify-center gap-1.5 mt-4">
                        <Lock className="w-3 h-3" /> Access restricted to @adit.com accounts
                    </div>
                </form>
            </div>
        </div>
    );
};
