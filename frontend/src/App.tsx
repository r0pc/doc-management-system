import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import { queryClient } from './lib/query-client';
import { AuthProvider } from './api/auth';
import { ThemeProvider } from './components/theme/ThemeProvider';
import { api } from './api/client';
import { AppLayout } from './components/layout/AppLayout';
import { DashboardPage } from './features/dashboard/DashboardPage';
import { DocumentsPage } from './features/documents/DocumentsPage';
import { UploadPage } from './features/upload/UploadPage';
import { ReviewPage } from './features/review/ReviewPage';
import { SearchPage } from './features/search/SearchPage';
import { AuditPage } from './features/audit/AuditPage';
import { TaxonomyPage } from './features/admin/TaxonomyPage';
import { LoginPage } from './features/auth/LoginPage';
import { RequireAuth } from './features/auth/RequireAuth';
import { usePermissions } from './security/usePermissions';
import { Action } from './security/permissions';

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

/**
 * Everything behind the guard. It only mounts for a session that exists, so it
 * may query the API on sight — the review-count poll below used to fire during
 * the auto-login bootstrap and 401 before a token was in hand.
 */
function AuthenticatedApp() {
  const { can } = usePermissions();

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

  return (
    <AppLayout reviewCount={pendingCount}>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/admin" element={<TaxonomyPage />} />
      </Routes>
    </AppLayout>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system">
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              {/* The only route reachable without a session. */}
              <Route path="/login" element={<LoginPage />} />
              <Route
                path="/*"
                element={
                  <RequireAuth>
                    <AuthenticatedApp />
                  </RequireAuth>
                }
              />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
