import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentsPage } from './DocumentsPage';
import {
  renderWithProviders,
  jsonResponse,
  PERSONA_ADMIN,
  PERSONA_VIEWER,
  PERSONA_EMPLOYEE,
} from '../../test-utils';

/**
 * Selecting and deleting documents.
 *
 * Deletion is gated on Action.DELETE, which only admin and security_officer
 * hold. The checkboxes and the delete button are cosmetic gating (#33) — the
 * server refuses regardless — but a viewer should not be shown a control that
 * will only ever 403.
 */

const DOCS = [
  { id: 'aaaaaaaa-0000-0000-0000-000000000001', filename: 'a.pdf', status: 'ready', level: 'Internal', doc_type: null, created_at: '2026-09-01T10:00:00Z' },
  { id: 'bbbbbbbb-0000-0000-0000-000000000002', filename: 'b.pdf', status: 'ready', level: 'Internal', doc_type: null, created_at: '2026-09-01T10:01:00Z' },
  { id: 'cccccccc-0000-0000-0000-000000000003', filename: 'c.pdf', status: 'failed', level: 'Internal', doc_type: null, created_at: '2026-09-01T10:02:00Z' },
];

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn((url: string) => {
    if (url.startsWith('/v1/documents?') || url === '/v1/documents')
      return Promise.resolve(jsonResponse({ items: DOCS, next_cursor: null }));
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const rowCheckbox = (filename: string) =>
  within(
    document.querySelector(`[data-testid="document-row"][data-filename="${filename}"]`)!
      .closest('tr') as HTMLElement
  ).getByRole('checkbox');

describe('DocumentsPage — selection', () => {
  it('renders a checkbox on every row for a privileged role', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_ADMIN });
    await screen.findByTestId('documents-table');
    expect(screen.getAllByTestId('row-select')).toHaveLength(DOCS.length);
  });

  it('selecting a row reveals the delete control with a count', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_ADMIN });
    await screen.findByTestId('documents-table');
    expect(screen.queryByTestId('delete-selected')).not.toBeInTheDocument();

    await userEvent.click(rowCheckbox('a.pdf'));
    expect(await screen.findByTestId('delete-selected')).toHaveTextContent(/1/);
  });

  it('select-all checks every row, and unchecks them again', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_ADMIN });
    await screen.findByTestId('documents-table');
    const all = screen.getByTestId('select-all');

    await userEvent.click(all);
    for (const box of screen.getAllByTestId('row-select')) {
      expect(box).toBeChecked();
    }
    expect(screen.getByTestId('delete-selected')).toHaveTextContent(/3/);

    await userEvent.click(all);
    for (const box of screen.getAllByTestId('row-select')) {
      expect(box).not.toBeChecked();
    }
  });

  it('select-all is indeterminate when only some rows are selected', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_ADMIN });
    await screen.findByTestId('documents-table');
    await userEvent.click(rowCheckbox('a.pdf'));
    expect((screen.getByTestId('select-all') as HTMLInputElement).indeterminate).toBe(true);
  });

  it('clicking a checkbox does not open the drawer', async () => {
    // The row itself is clickable; the checkbox must not inherit that.
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_ADMIN });
    await screen.findByTestId('documents-table');
    await userEvent.click(rowCheckbox('a.pdf'));
    expect(screen.queryByTestId('drawer')).not.toBeInTheDocument();
  });
});

describe('DocumentsPage — deletion', () => {
  it('asks for confirmation before deleting', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_ADMIN });
    await screen.findByTestId('documents-table');
    await userEvent.click(rowCheckbox('a.pdf'));
    await userEvent.click(screen.getByTestId('delete-selected'));

    expect(await screen.findByTestId('confirm-delete')).toBeInTheDocument();
    // Nothing is sent until the user confirms.
    expect(
      fetchMock.mock.calls.filter((c) => String(c[0]).includes('/documents/delete'))
    ).toHaveLength(0);
  });

  it('posts the selected ids once confirmed', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_ADMIN });
    await screen.findByTestId('documents-table');
    await userEvent.click(rowCheckbox('a.pdf'));
    await userEvent.click(rowCheckbox('c.pdf'));
    await userEvent.click(screen.getByTestId('delete-selected'));
    await userEvent.click(await screen.findByTestId('confirm-delete'));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/documents/delete'));
      expect(call, 'no delete request was sent').toBeTruthy();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.document_ids).toEqual([DOCS[0].id, DOCS[2].id]);
    });
  });

  it('cancelling sends nothing and keeps the selection', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_ADMIN });
    await screen.findByTestId('documents-table');
    await userEvent.click(rowCheckbox('a.pdf'));
    await userEvent.click(screen.getByTestId('delete-selected'));
    await userEvent.click(await screen.findByTestId('cancel-delete'));

    expect(
      fetchMock.mock.calls.filter((c) => String(c[0]).includes('/documents/delete'))
    ).toHaveLength(0);
    expect(screen.getByTestId('delete-selected')).toHaveTextContent(/1/);
  });
});

describe('DocumentsPage — deletion is gated (#33 cosmetic)', () => {
  it('a viewer sees no checkboxes and no delete control', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_VIEWER });
    await screen.findByTestId('documents-table');
    expect(screen.queryAllByTestId('row-select')).toHaveLength(0);
    expect(screen.queryByTestId('select-all')).not.toBeInTheDocument();
    expect(screen.queryByTestId('delete-selected')).not.toBeInTheDocument();
  });

  it('an employee sees no delete control either', async () => {
    renderWithProviders(<DocumentsPage />, { persona: PERSONA_EMPLOYEE });
    await screen.findByTestId('documents-table');
    expect(screen.queryByTestId('select-all')).not.toBeInTheDocument();
  });
});
