import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { DashboardPage } from './DashboardPage';
import { api } from '../../api/client';
import { DocumentStatsOut } from '../../api/types';
import { renderWithProviders, PERSONA_ADMIN } from '../../test-utils';

const mockStats: DocumentStatsOut = {
  total_documents: 42,
  total_storage_bytes: 5242880,
  status_breakdown: {
    ready: 38,
    processing: 2,
    quarantined: 0,
    failed: 1,
    held: 1,
  },
  levels_breakdown: [
    { name: 'Public', rank: 1, count: 10, percentage: 23.8 },
    { name: 'Internal', rank: 2, count: 20, percentage: 47.6 },
    { name: 'Confidential', rank: 3, count: 8, percentage: 19.0 },
    { name: 'Restricted', rank: 4, count: 4, percentage: 9.5 },
  ],
  doc_types_breakdown: [
    { name: 'Vendor MSA', count: 18, percentage: 42.9 },
    { name: 'Financial Statement', count: 14, percentage: 33.3 },
    { name: 'Security Policy', count: 10, percentage: 23.8 },
  ],
  departments_breakdown: [
    { id: '11111111-1111-1111-1111-111111111111', name: 'HQ', count: 42 },
    { id: '22222222-2222-2222-2222-222222222222', name: 'Engineering', count: 25 },
  ],
  decision_sources: [
    { source: 'ml', count: 30 },
    { source: 'rule', count: 8 },
    { source: 'human', count: 4 },
  ],
  daily_ingestion: [
    { date: '2026-09-01', count: 12 },
    { date: '2026-09-02', count: 30 },
  ],
  recent_documents: [
    {
      id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      filename: 'Q3_Financials.pdf',
      status: 'ready',
      level: 'Confidential',
      doc_type: 'Financial Statement',
      created_at: '2026-09-02T10:00:00Z',
    },
    {
      id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      filename: 'Vendor_Agreement.pdf',
      status: 'ready',
      level: 'Internal',
      doc_type: 'Vendor MSA',
      created_at: '2026-09-02T09:30:00Z',
    },
  ],
  avg_confidence: 0.942,
  pending_reviews_count: 3,
};

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const renderComponent = () => {
    return renderWithProviders(<DashboardPage />, {
      persona: PERSONA_ADMIN,
    });
  };

  it('renders KPI metrics and summaries accurately', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/documents/stats') return mockStats;
      return [];
    });
    renderComponent();

    expect(await screen.findByText(/90% ready/i)).toBeInTheDocument();
    expect(screen.getAllByText('42').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('12')).toBeInTheDocument(); // 4 Restricted + 8 Conf.
    expect(screen.getByText('3')).toBeInTheDocument(); // Pending Reviews
    expect(screen.getByText('5 MiB')).toBeInTheDocument();
    expect(screen.getByText(/94.2% avg conf/i)).toBeInTheDocument();
  });

  it('renders security levels distribution and taxonomy breakdown', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/documents/stats') return mockStats;
      return [];
    });
    renderComponent();

    expect((await screen.findAllByText('Vendor MSA'))[0]).toBeInTheDocument();
    expect(screen.getByText('Security Level Distribution')).toBeInTheDocument();
    expect(screen.getAllByText('Public').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Financial Statement').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Security Policy')).toBeInTheDocument();
  });

  it('renders pipeline health and department volume', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/documents/stats') return mockStats;
      return [];
    });
    renderComponent();

    expect((await screen.findAllByText('Engineering'))[0]).toBeInTheDocument();
    expect(screen.getByText('Processing Pipeline Health')).toBeInTheDocument();
    expect(screen.getByText('Department Visibility')).toBeInTheDocument();
    expect(screen.getAllByText('HQ').length).toBeGreaterThanOrEqual(1);
  });

  it('renders recently ingested documents list', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/documents/stats') return mockStats;
      return [];
    });
    renderComponent();

    expect(await screen.findByText('Q3_Financials.pdf')).toBeInTheDocument();
    expect(screen.getByText('Vendor_Agreement.pdf')).toBeInTheDocument();
  });

  it('allows clicking refresh button to refetch stats', async () => {
    const getSpy = vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/documents/stats') return mockStats;
      return [];
    });
    renderComponent();

    expect(await screen.findByText('Q3_Financials.pdf')).toBeInTheDocument();
    const refreshBtn = screen.getByRole('button', { name: /refresh dashboard data/i });
    fireEvent.click(refreshBtn);

    await waitFor(() => {
      const statsCalls = getSpy.mock.calls.filter((c) => c[0] === '/v1/documents/stats');
      expect(statsCalls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
