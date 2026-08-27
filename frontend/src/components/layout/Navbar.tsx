import React from 'react';
import { UserSwitcher } from './UserSwitcher';
import { ThemeToggle } from '../theme/ThemeToggle';
import { Shield, Sparkles } from 'lucide-react';

export const Navbar: React.FC = () => {
  return (
    <header className="h-14 border-b border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#161b22] px-6 flex items-center justify-between sticky top-0 z-30 transition-colors">
      <div className="flex items-center gap-3">
        <div className="p-1.5 rounded-md bg-[#0969da] dark:bg-[#2f81f7] text-white shadow-xs flex items-center justify-center">
          <Shield className="w-4 h-4" />
        </div>
        <div>
          <h1 className="font-semibold text-[#1f2328] dark:text-[#e6edf3] text-sm leading-tight tracking-tight flex items-center gap-2">
            Secure DMS
            <span className="text-[10px] font-mono font-medium px-1.5 py-0.2 rounded-full bg-[#ddf4ff] text-[#0969da] dark:bg-[#388bfd]/20 dark:text-[#58a6ff] border border-[#54aeff]/30">
              v1.0
            </span>
          </h1>
          <p className="text-[11px] text-[#656d76] dark:text-[#848d97] hidden sm:block">
            Self-Hosted Classification & Multi-Tenant Access Control
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="hidden md:flex items-center gap-1.5 text-[11px] text-[#1a7f37] dark:text-[#3fb950] bg-[#dafbe1] dark:bg-[#238636]/20 px-2 py-0.5 rounded-md border border-[#4ac26b]/40 font-medium">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Airgapped & Self-Hosted</span>
        </div>
        <ThemeToggle />
        <UserSwitcher />
      </div>
    </header>
  );
};
