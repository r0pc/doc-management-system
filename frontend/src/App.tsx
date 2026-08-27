import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import { queryClient } from './lib/query-client';
import { AuthProvider } from './api/auth';
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
