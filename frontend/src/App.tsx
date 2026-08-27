import { useState } from 'react';
import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import { queryClient } from './lib/query-client';
import { AuthProvider } from './api/auth';
import { ThemeProvider } from './components/theme/ThemeProvider';
import { api } from './api/client';
import { ReviewQueueItem, CursorPaginated } from './api/types';
import { AppLayout } from './components/layout/AppLayout';
import { NavTab } from './components/layout/Sidebar';
import { DocumentsPage } from './features/documents/DocumentsPage';
import { UploadPage } from './features/upload/UploadPage';
import { ReviewPage } from './features/review/ReviewPage';
import { SearchPage } from './features/search/SearchPage';
import { AuditPage } from './features/audit/AuditPage';
import { TaxonomyPage } from './features/admin/TaxonomyPage';

function AppContent() {
  const [currentTab, setCurrentTab] = useState<NavTab>('documents');

  // Query pending reviews for badge count
  const { data: reviewData } = useQuery({
    queryKey: ['review', 'pending'],
    queryFn: () =>
      api.get<CursorPaginated<ReviewQueueItem> | ReviewQueueItem[]>('/v1/review', {
        status: 'pending',
        limit: 100,
      }),
    refetchInterval: 15000,
  });

  const pendingCount = Array.isArray(reviewData)
    ? reviewData.length
    : reviewData?.items?.length || 0;

  return (
    <AppLayout
      currentTab={currentTab}
      onSelectTab={setCurrentTab}
      reviewCount={pendingCount}
    >
      {currentTab === 'documents' && (
        <DocumentsPage onNavigateUpload={() => setCurrentTab('upload')} />
      )}
      {currentTab === 'upload' && (
        <UploadPage onUploadComplete={() => setCurrentTab('documents')} />
      )}
      {currentTab === 'review' && <ReviewPage />}
      {currentTab === 'search' && <SearchPage />}
      {currentTab === 'audit' && <AuditPage />}
      {currentTab === 'admin' && <TaxonomyPage />}
    </AppLayout>
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
