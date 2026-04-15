import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

const customTwMerge = extendTailwindMerge({
    extend: {
        colors: [
            "obsidian-bg", "obsidian-surface", "obsidian-card", "obsidian-border", "obsidian-border2",
            "neon-blue", "neon-blue-dim", "amber-gold", "amber-gold-dim", "crimson-red", "crimson-red-dim",
            "green-ok", "purple-dev", "text-primary", "text-muted", "text-faint"
        ]
    }
})

export function cn(...inputs: ClassValue[]) {
  return customTwMerge(clsx(inputs))
}
