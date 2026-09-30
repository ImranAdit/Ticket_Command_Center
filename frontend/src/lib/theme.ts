import { useEffect, useState } from 'react';

// Dark is the original look; light is optional. The choice is remembered per browser.
export type Theme = 'dark' | 'light';
const KEY = 'tcc-theme';

const read = (): Theme => {
    try { return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'; } catch { return 'dark'; }
};

const apply = (t: Theme) => {
    document.documentElement.dataset.theme = t;
};

// Apply as soon as the app loads (sign-in page included) to avoid a flash of the wrong theme
apply(read());

export const useTheme = () => {
    const [theme, setTheme] = useState<Theme>(read);
    useEffect(() => {
        apply(theme);
        try { localStorage.setItem(KEY, theme); } catch { /* private mode: still works for this visit */ }
    }, [theme]);
    return { theme, toggle: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')) };
};
