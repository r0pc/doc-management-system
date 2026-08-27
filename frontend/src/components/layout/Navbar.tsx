import React from 'react';
import { UserSwitcher } from './UserSwitcher';
import { ThemeToggle } from '../theme/ThemeToggle';
import { Shield, Sparkles } from 'lucide-react';

export const Navbar: React.FC = () => {
  return (
    <header className="h-16 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-6 flex items-center justify-between sticky top-0 z-30 shadow-xs transition-colors">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-xl bg-blue-600 text-white shadow-sm flex items-center justify-center">
          <Shield className="w-5 h-5" />
        </div>
        <div>
          <h1 className="font-bold text-slate-900 dark:text-slate-100 text-base leading-tight tracking-tight flex items-center gap-2">
            Secure DMS
            <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900/60 dark:text-blue-200">
              v1.0
            </span>
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 hidden sm:block">
            Self-Hosted Classification & Multi-Tenant Access Control
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="hidden md:flex items-center gap-1.5 text-xs text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/40 px-2.5 py-1 rounded-full border border-emerald-200 dark:border-emerald-800 font-medium">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Airgapped & Self-Hosted</span>
        </div>
        <ThemeToggle />
        <UserSwitcher />
      </div>
    </header>
  );
};
