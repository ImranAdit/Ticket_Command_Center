import React, { useState } from 'react';
import { cn } from '../lib/utils';
import { Lock, Loader2, ArrowRight } from 'lucide-react';
import { useGoogleLogin } from '@react-oauth/google';

interface AuthGateProps {
    onLogin: (email: string) => void;
}

export const AuthGate: React.FC<AuthGateProps> = ({ onLogin }) => {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const validateAndLogin = (email: string) => {
        const cleanEmail = email.trim().toLowerCase();

        if (!cleanEmail.endsWith('@adit.com')) {
            setError('Access restricted to @adit.com accounts only. Access Denied.');
            setLoading(false);
            return;
        }

        localStorage.setItem('lastAditEmail', cleanEmail);
        onLogin(cleanEmail);
        setLoading(false);
    };

    const login = useGoogleLogin({
        onSuccess: async (tokenResponse) => {
            try {
                setLoading(true);
                setError(null);

                // Fetch user info from Google
                const res = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', {
                    headers: {
                        Authorization: `Bearer ${tokenResponse.access_token}`,
                    },
                });

                const user = await res.json();

                if (!user?.email) {
                    throw new Error('Unable to fetch email from Google');
                }

                validateAndLogin(user.email);
            } catch (err) {
                setError('Google login failed. Please try again.');
                setLoading(false);
            }
        },
        onError: () => {
            setError('Google login failed. Please try again.');
            setLoading(false);
        },
        scope: 'openid profile email',
    });

    const handleMainAction = () => {
        if (loading) return;
        setError(null);
        login();
    };

    return (
        <div className="flex bg-obsidian-bg items-center justify-center min-h-screen relative overflow-hidden">
            <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(0, 180, 255, 0.15) 0%, transparent 75%)' }}></div>
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-neon-blue/5 rounded-full blur-[120px] pointer-events-none animate-pulse"></div>

            <div className="glass-card p-12 w-[440px] max-w-full relative z-10 flex flex-col items-center">
                <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[70%] h-[1px] bg-gradient-to-r from-transparent via-neon-blue to-transparent shadow-[0_0_15px_rgba(0,180,255,0.5)]"></div>

                <div className="mb-4 flex items-center justify-center">
                    <img
                        src="https://adit.com/storage/settings/logo.png"
                        alt="Adit"
                        className="h-[52px] object-contain"
                    />
                </div>

                <div className="text-[10px] text-text-muted text-center tracking-[5px] uppercase mb-12 mt-2 font-bold opacity-80">
                    Ticket Command Center
                </div>

                <div className="w-full flex flex-col items-center">
                    <button
                        onClick={handleMainAction}
                        disabled={loading}
                        className={cn(
                            "group relative w-full h-[64px] rounded-xl flex items-center justify-center gap-4 transition-all duration-500",
                            "stunning-btn-glass stunning-btn-glow",
                            loading ? "opacity-90 cursor-wait" : "cursor-pointer active:scale-[0.98]"
                        )}
                    >
                        <div className="absolute inset-0 rounded-xl overflow-hidden pointer-events-none">
                            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover:animate-[sweep_1.5s_ease-in-out_infinite]"></div>
                        </div>

                        {loading ? (
                            <Loader2 className="w-6 h-6 animate-spin text-neon-blue" />
                        ) : (
                            <>
                                <div className="p-2.5 bg-white rounded-lg flex items-center justify-center shadow-lg">
                                    <svg viewBox="0 0 24 24" width="20" height="20">
                                        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                                        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                                        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05" />
                                        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.66l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                                    </svg>
                                </div>
                                <span className="text-[15px] font-bold text-text-primary tracking-wide">
                                    Sign in with Google
                                </span>
                                <ArrowRight className="w-5 h-5 text-neon-blue opacity-50 group-hover:opacity-100 group-hover:translate-x-1 transition-all" />
                            </>
                        )}
                    </button>

                    {error && (
                        <div className="mt-6 text-[11px] text-crimson-red bg-crimson-red/10 border border-crimson-red/20 py-2.5 px-4 rounded-lg text-center w-full">
                            {error}
                        </div>
                    )}

                    <div className="text-[11px] text-text-faint flex items-center justify-center gap-2 mt-10">
                        <Lock className="w-3.5 h-3.5" />
                        <span className="tracking-tight font-medium uppercase opacity-50">
                            Sign in using your Adit account
                        </span>
                    </div>
                </div>
            </div>
        </div>
    );
};
