import React from 'react';
import { UserSwitcher } from './UserSwitcher';
import { useAuth } from '../../api/auth';
import { ThemeToggle } from '../theme/ThemeToggle';
import { Shield } from 'lucide-react';

export const Navbar: React.FC = () => {
  // The demo account switcher re-signs-in from published credentials. It is
  // only ever rendered when the backend's demo login endpoint can exist at all;
  // in a production build `demoLoginEnabled` is a compile-time `false` and this
  // whole subtree is dropped from the bundle.
  const { demoLoginEnabled } = useAuth();

  return (
    <header className="h-14 border-b border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#161b22] px-6 flex items-center justify-between sticky top-0 z-30 transition-colors">
      <div className="flex items-center gap-3">
        <div className="p-1.5 rounded-md bg-[#0969da] dark:bg-[#2f81f7] text-white shadow-xs flex items-center justify-center">
          <Shield className="w-4 h-4" />
        </div>
        <div>
          <h1 className="font-semibold text-[#1f2328] dark:text-[#e6edf3] text-sm leading-tight tracking-tight flex items-center gap-2">
            Secure DMS
          </h1>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <ThemeToggle />
        {demoLoginEnabled && <UserSwitcher />}
      </div>
    </header>
  );
};
