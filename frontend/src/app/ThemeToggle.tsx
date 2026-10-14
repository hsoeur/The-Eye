import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme, type Theme } from "@/lib/theme";

const opts: { id: Theme; icon: typeof Sun; label: string }[] = [
  { id: "light", icon: Sun, label: "Clair" },
  { id: "system", icon: Monitor, label: "Système" },
  { id: "dark", icon: Moon, label: "Sombre" },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div role="radiogroup" aria-label="Thème" className="flex rounded-md border bg-surface p-0.5">
      {opts.map(({ id, icon: Icon, label }) => (
        <button key={id} role="radio" aria-checked={theme === id} aria-label={label} title={label} onClick={() => setTheme(id)}
          className={cn("flex h-6 flex-1 items-center justify-center rounded text-muted transition-colors hover:text-fg", theme === id && "bg-raised text-fg")}>
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  );
}
