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

  const nextTheme = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light';

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={cycleTheme}
      className="h-8 w-8 rounded-lg text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
      title={`Theme: ${theme}. Activate to switch to ${nextTheme}.`}
      // A three-state cycle: the label has to name BOTH the current state and
      // what activation does, or a screen-reader user cannot tell where in the
      // cycle they are. The icon alone conveys nothing (lucide marks it
      // aria-hidden).
      aria-label={`Theme: ${theme}. Switch to ${nextTheme} theme.`}
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
