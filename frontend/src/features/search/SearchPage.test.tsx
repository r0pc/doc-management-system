import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchPage } from './SearchPage';
import {
  renderWithProviders,
  jsonResponse,
  PERSONA_ADMIN,
  PERSONA_VIEWER,
} from '../../test-utils';

const mockSearchResponse = {
  results: [
    {
      version_id: '11111111-1111-1111-1111-111111111111',
      document_id: '22222222-2222-2222-2222-222222222222',
      filename: 'annual_report.pdf',
      level: 'Internal',
      doc_type: 'Report',
      snippet: 'This is the annual financial overview.',
      score: 0.032,
    },
  ],
  facets: {
    levels: { internal: 1, confidential: 0 },
    doc_types: { Report: 1 },
  },
  total_candidates: 1,
};

const mockDepartments = [
  { id: 'dept-hq', name: 'HQ', parent_id: null, is_root: true, assignable: true },
  { id: 'dept-hr', name: 'HR', parent_id: 'dept-hq', is_root: false, assignable: true },
  { id: 'dept-fin', name: 'Finance', parent_id: 'dept-hq', is_root: false, assignable: true },
];

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn((url: string) => {
    if (String(url).includes('/v1/departments')) {
      return Promise.resolve(jsonResponse(mockDepartments));
    }
    if (String(url).includes('/v1/admin/doc-types')) {
      return Promise.resolve(
        jsonResponse([
          { id: 'dt-1', name: 'Contract', parent_id: null, description: '' },
          { id: 'dt-2', name: 'Report', parent_id: null, description: '' },
        ])
      );
    }
    if (String(url).includes('/v1/search')) {
      return Promise.resolve(jsonResponse(mockSearchResponse));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('SearchPage', () => {
  it('renders search bar and filters bar in initial empty state', async () => {
    renderWithProviders(<SearchPage />, { persona: PERSONA_ADMIN });

    expect(screen.getByLabelText(/search query/i)).toBeInTheDocument();
    expect(screen.getByTestId('search-filter-level')).toBeInTheDocument();
    expect(screen.getByTestId('search-filter-doctype')).toBeInTheDocument();
    expect(await screen.findByTestId('search-filter-department')).toBeInTheDocument();
    expect(screen.getByText(/search your repository/i)).toBeInTheDocument();
  });

  it('an admin sees the Department filter dropdown', async () => {
    renderWithProviders(<SearchPage />, { persona: PERSONA_ADMIN });
    expect(await screen.findByTestId('search-filter-department')).toBeInTheDocument();
    expect(screen.getByText(/HQ \(Root\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Finance/i)).toBeInTheDocument();
  });

  it('a viewer role does not see the Department filter dropdown', async () => {
    renderWithProviders(<SearchPage />, { persona: PERSONA_VIEWER });
    expect(screen.getByTestId('search-filter-level')).toBeInTheDocument();
    expect(screen.queryByTestId('search-filter-department')).not.toBeInTheDocument();
  });

  it('executes search with query, level, and department filters', async () => {
    const user = userEvent.setup();
    renderWithProviders(<SearchPage />, { persona: PERSONA_ADMIN });

    const input = screen.getByLabelText(/search query/i);
    await user.type(input, 'financial overview');

    const levelSelect = screen.getByTestId('search-filter-level');
    fireEvent.change(levelSelect, { target: { value: 'internal' } });

    const deptSelect = await screen.findByTestId('search-filter-department');
    fireEvent.change(deptSelect, { target: { value: 'dept-fin' } });

    const searchButton = screen.getByRole('button', { name: /search/i });
    await user.click(searchButton);

    await waitFor(() => {
      const searchCalls = fetchMock.mock.calls.filter((c) =>
        String(c[0]).includes('/v1/search')
      );
      expect(searchCalls.length).toBeGreaterThan(0);
      const url = String(searchCalls[searchCalls.length - 1][0]);
      expect(url).toContain('q=financial+overview');
      expect(url).toContain('level=internal');
      expect(url).toContain('department_id=dept-fin');
    });

    expect(await screen.findByText('annual_report.pdf')).toBeInTheDocument();
    expect(screen.getByText(/This is the annual financial overview/i)).toBeInTheDocument();
  });

  it('allows clearing all filters with the clear button', async () => {
    const user = userEvent.setup();
    renderWithProviders(<SearchPage />, {
      route: '/search?q=test&level=confidential',
      persona: PERSONA_ADMIN,
    });

    const clearButton = await screen.findByTestId('search-clear-filters');
    await user.click(clearButton);

    const input = screen.getByLabelText(/search query/i) as HTMLInputElement;
    expect(input.value).toBe('');
    expect(screen.queryByTestId('search-clear-filters')).not.toBeInTheDocument();
  });
});
