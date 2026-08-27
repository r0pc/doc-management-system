import React from 'react';
import { Navbar } from './Navbar';
import { Sidebar } from './Sidebar';

interface AppLayoutProps {
  reviewCount?: number;
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({
  reviewCount,
  children,
}) => {
  return (
    <div className="min-h-screen flex flex-col bg-primer-canvas-default dark:bg-primer-canvas-default-dark text-primer-fg-default dark:text-primer-fg-default-dark transition-colors font-sans">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar
          reviewCount={reviewCount}
        />
        <main className="flex-1 p-6 md:p-8 max-w-7xl mx-auto w-full overflow-y-auto bg-primer-canvas-default dark:bg-primer-canvas-default-dark">
          {children}
        </main>
      </div>
    </div>
  );
};
