import React, { useState } from 'react';
import { cn } from '../lib/utils';
import { Hexagon, Lock, Component } from 'lucide-react';

interface AuthGateProps {
    onLogin: (email: string) => void;
}

export const AuthGate: React.FC<AuthGateProps> = ({ onLogin }) => {
    const [loading, setLoading] = useState(false);

    const handleGoogleSSO = () => {
        setLoading(true);
        // Simulate OAuth / Google Workspace redirect delay
        setTimeout(() => {
            setLoading(false);
            onLogin('demo@adit.com');
        }, 1500);
    };

    return (
        <div className="flex bg-obsidian-bg items-center justify-center min-h-screen relative overflow-hidden">
            <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(0, 180, 255, 0.12) 0%, transparent 70%)' }}></div>
            
            <div className="glass-card p-10 w-[420px] max-w-full relative z-10 flex flex-col items-center">
                <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[60%] h-[1px] bg-gradient-to-r from-transparent via-neon-blue to-transparent"></div>
                
                {/* Branding Replacements */}
                <div className="mb-2">
                    <img 
                        src="https://cdn.prod.website-files.com/5f918e698188185fe8e76a16/5fac664dfdb1fb671c667086_adit-logo.svg" 
                        alt="Adit Logo" 
                        className="h-[36px] object-contain drop-shadow-[0_0_8px_rgba(255,255,255,0.2)] dark:invert"
                        onError={(e) => {
                            // Fallback to text if missing
                            e.currentTarget.style.display = 'none';
                            e.currentTarget.nextElementSibling?.classList.remove('hidden');
                        }}
                    />
                    {/* Fallback Text if image fails */}
                    <div className="text-[28px] font-bold text-text-primary tracking-[2px] text-center hidden flex items-center justify-center gap-2">
                        ADIT <Hexagon className="w-6 h-6 text-neon-blue fill-neon-blue" />
                    </div>
                </div>
                
                <div className="text-[11px] text-text-muted text-center tracking-[3px] uppercase mb-10 mt-2">
                    Ticket Command Center
                </div>

                {/* Google Workspace / Adit Login Flow */}
                <div className="w-full flex flex-col gap-4">
                    <button 
                        onClick={handleGoogleSSO}
                        disabled={loading}
                        className={cn(
                            "w-full flex items-center justify-center gap-3 py-3 px-4 bg-obsidian-surface border border-obsidian-border2 rounded-lg text-text-primary text-[13px] font-medium cursor-pointer transition-all duration-200",
                            "hover:bg-obsidian-card hover:border-text-muted hover:shadow-[0_0_15px_rgba(0,180,255,0.15)]",
                            loading && "opacity-70 cursor-not-allowed"
                        )}
                    >
                        {loading ? (
                            <Component className="w-5 h-5 animate-spin text-neon-blue" />
                        ) : (
                            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                            </svg>
                        )}
                        {loading ? 'Authenticating with Google...' : 'Sign in with Adit Workspace'}
                    </button>
                    
                    <div className="text-[11px] text-text-faint flex items-center justify-center gap-1.5 mt-4">
                        <Lock className="w-3 h-3" /> Secure Google SSO automatically validates @adit.com
                    </div>
                </div>
            </div>
        </div>
    );
};
