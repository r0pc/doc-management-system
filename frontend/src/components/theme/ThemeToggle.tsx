import { Moon, Sun, Laptop } from 'lucide-react';
import { useTheme } from './ThemeProvider';
import { Button } from '../ui/button';

export function ThemeToggle() {
  const { theme, setTheme, isDark } = useTheme();

  const cycleTheme = () => {
    if (theme === 'light') setTheme('dark');
    else if (theme === 'dark') setTheme('system');
    else setTheme('light');
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={cycleTheme}
      className="h-8 w-8 rounded-lg text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
      title={`Current theme: ${theme} (Click to toggle)`}
      aria-label="Toggle theme"
    >
      {theme === 'system' ? (
        <Laptop className="h-4 w-4" />
      ) : isDark ? (
        <Moon className="h-4 w-4 text-blue-400" />
      ) : (
        <Sun className="h-4 w-4 text-amber-500" />
      )}
    </Button>
  );
}
