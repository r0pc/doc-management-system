import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import { queryClient } from './lib/query-client';
import { AuthProvider, useAuth } from './api/auth';
import { ThemeProvider } from './components/theme/ThemeProvider';
import { api } from './api/client';
import { AppLayout } from './components/layout/AppLayout';
import { DocumentsPage } from './features/documents/DocumentsPage';
import { UploadPage } from './features/upload/UploadPage';
import { ReviewPage } from './features/review/ReviewPage';
import { SearchPage } from './features/search/SearchPage';
import { AuditPage } from './features/audit/AuditPage';
import { TaxonomyPage } from './features/admin/TaxonomyPage';
import { usePermissions } from './security/usePermissions';
import { Action } from './security/permissions';

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

function AppContent() {
  const { can } = usePermissions();
  const { authReady, authError, user } = useAuth();
  
  // Query pending reviews for badge count
  const { data: reviewData } = useQuery({
    queryKey: ['review', 'pending'],
    queryFn: () =>
      api.get<any>('/v1/review', {
        limit: 100,
      }),
    refetchInterval: 15000,
    enabled: can(Action.RESOLVE_REVIEW),
  });

  const pendingCount = Array.isArray(reviewData)
    ? reviewData.length
    : reviewData?.items?.length || 0;

  if (!authReady) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-[#656d76]">
        Establishing session...
      </div>
    );
  }

  // Fail visibly rather than rendering a full application shell for a session
  // that has no credentials. Previously a failed token mint left the persona's
  // claims in place, so the UI drew an admin nav over an unauthenticated
  // client and every request 401'd behind a blank page.
  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div
          role="alert"
          className="max-w-md rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#161b22] p-5 text-sm"
        >
          <h1 className="font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">Not signed in</h1>
          <p className="text-xs text-[#656d76] dark:text-[#848d97] leading-relaxed">
            {authError ??
              'No session could be established. Sign in to continue.'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <AppLayout reviewCount={pendingCount}>
        <Routes>
          <Route path="/" element={<Navigate to="/documents" replace />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/admin" element={<TaxonomyPage />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system">
        <AuthProvider>
          <AppContent />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
