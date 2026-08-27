import React from 'react';
import { Navbar } from './Navbar';
import { Sidebar, NavTab } from './Sidebar';

interface AppLayoutProps {
  currentTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
  reviewCount?: number;
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({
  currentTab,
  onSelectTab,
  reviewCount,
  children,
}) => {
  return (
    <div className="min-h-screen flex flex-col bg-[#ffffff] dark:bg-[#0d1117] text-[#1f2328] dark:text-[#e6edf3] transition-colors font-sans">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar
          currentTab={currentTab}
          onSelectTab={onSelectTab}
          reviewCount={reviewCount}
        />
        <main className="flex-1 p-6 md:p-8 max-w-7xl mx-auto w-full overflow-y-auto bg-white dark:bg-[#0d1117]">
          {children}
        </main>
      </div>
    </div>
  );
};
