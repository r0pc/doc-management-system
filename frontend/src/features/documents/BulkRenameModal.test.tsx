import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BulkRenameModal } from './BulkRenameModal';
import { api } from '../../api/client';
import { DocumentListItem } from '../../api/types';
import { renderWithProviders, PERSONA_ADMIN } from '../../test-utils';

const mockDocs: DocumentListItem[] = [
  {
    id: 'doc-1',
    filename: 'annual_report_draft.pdf',
    status: 'ready',
    level: 'Internal',
    doc_type: 'Report',
    created_at: '2026-09-01T10:00:00Z',
  },
  {
    id: 'doc-2',
    filename: 'invoice_draft.pdf',
    status: 'ready',
    level: 'Internal',
    doc_type: 'Invoice',
    created_at: '2026-09-01T10:00:00Z',
  },
];

describe('BulkRenameModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders selected documents in the transformation preview table', () => {
    renderWithProviders(
      <BulkRenameModal
        isOpen={true}
        documents={mockDocs}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
      { persona: PERSONA_ADMIN }
    );

    expect(screen.getByText(/bulk rename documents \(2 selected\)/i)).toBeInTheDocument();
    expect(screen.getByText('annual_report_draft.pdf')).toBeInTheDocument();
    expect(screen.getByText('invoice_draft.pdf')).toBeInTheDocument();
  });

  it('applies prefix and suffix while preserving file extension', async () => {
    renderWithProviders(
      <BulkRenameModal
        isOpen={true}
        documents={mockDocs}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
      { persona: PERSONA_ADMIN }
    );

    const prefixInput = screen.getByLabelText(/add prefix to filenames/i);
    const suffixInput = screen.getByLabelText(/add suffix to filenames/i);

    fireEvent.change(prefixInput, { target: { value: '[2026] ' } });
    fireEvent.change(suffixInput, { target: { value: '_final' } });

    const input1 = screen.getByLabelText(/new filename for annual_report_draft\.pdf/i) as HTMLInputElement;
    const input2 = screen.getByLabelText(/new filename for invoice_draft\.pdf/i) as HTMLInputElement;

    expect(input1.value).toBe('[2026] annual_report_draft_final.pdf');
    expect(input2.value).toBe('[2026] invoice_draft_final.pdf');
    expect(screen.getByText('2 of 2 filename(s) will change')).toBeInTheDocument();
  });

  it('applies find and replace transformation and submits on Apply', async () => {
    const user = userEvent.setup();
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      renamed: ['doc-1', 'doc-2'],
    });
    const onClose = vi.fn();
    const onSuccess = vi.fn();

    renderWithProviders(
      <BulkRenameModal
        isOpen={true}
        documents={mockDocs}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
      { persona: PERSONA_ADMIN }
    );

    const findInput = screen.getByLabelText(/find text in filenames/i);
    const replaceInput = screen.getByLabelText(/replace text in filenames/i);

    await user.type(findInput, 'draft');
    await user.type(replaceInput, 'approved');

    const input1 = screen.getByLabelText(/new filename for annual_report_draft\.pdf/i) as HTMLInputElement;
    expect(input1.value).toBe('annual_report_approved.pdf');

    const applyButton = screen.getByRole('button', { name: /apply rename \(2\)/i });
    expect(applyButton).toBeEnabled();

    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith('/v1/documents/bulk-rename', {
        items: [
          { document_id: 'doc-1', new_filename: 'annual_report_approved.pdf' },
          { document_id: 'doc-2', new_filename: 'invoice_approved.pdf' },
        ],
      });
      expect(onSuccess).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });
});
