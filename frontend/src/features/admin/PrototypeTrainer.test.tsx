import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PrototypeTrainer } from './PrototypeTrainer';
import { api } from '../../api/client';
import { DocTypeOut, DocTypePrototypeOut, DocumentPage } from '../../api/types';
import { renderWithProviders, PERSONA_ADMIN } from '../../test-utils';

const mockDocTypes: DocTypeOut[] = [
  {
    id: 'dt-00000000-0000-0000-0000-000000000001',
    name: 'Vendor MSA',
    description: 'Master service agreement',
    parent_id: null,
  },
  {
    id: 'dt-00000000-0000-0000-0000-000000000002',
    name: 'Invoice',
    description: 'Billing invoice',
    parent_id: null,
  },
];

const mockPrototypes: DocTypePrototypeOut[] = [
  {
    id: 'proto-1',
    doc_type_id: 'dt-00000000-0000-0000-0000-000000000001',
    sample_count: 5,
    updated_at: '2026-09-01T12:00:00Z',
  },
];

const mockDocsPage: DocumentPage = {
  items: [
    {
      id: 'doc-00000000-0000-0000-0000-000000000001',
      filename: 'sample_1.pdf',
      status: 'ready',
      level: 'Internal',
      doc_type: 'Vendor MSA',
      created_at: '2026-09-01T10:00:00Z',
    },
    {
      id: 'doc-00000000-0000-0000-0000-000000000002',
      filename: 'sample_2.pdf',
      status: 'ready',
      level: 'Internal',
      doc_type: 'Vendor MSA',
      created_at: '2026-09-01T10:00:00Z',
    },
    {
      id: 'doc-00000000-0000-0000-0000-000000000003',
      filename: 'sample_3.pdf',
      status: 'ready',
      level: 'Internal',
      doc_type: 'Vendor MSA',
      created_at: '2026-09-01T10:00:00Z',
    },
    {
      id: 'doc-00000000-0000-0000-0000-000000000004',
      filename: 'sample_4.pdf',
      status: 'ready',
      level: 'Internal',
      doc_type: 'Vendor MSA',
      created_at: '2026-09-01T10:00:00Z',
    },
    {
      id: 'doc-00000000-0000-0000-0000-000000000005',
      filename: 'sample_5.pdf',
      status: 'ready',
      level: 'Internal',
      doc_type: 'Vendor MSA',
      created_at: '2026-09-01T10:00:00Z',
    },
  ],
  next_cursor: null,
};

describe('PrototypeTrainer', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const renderComponent = () => {
    return renderWithProviders(<PrototypeTrainer />, {
      persona: PERSONA_ADMIN,
    });
  };

  it('renders target doc type picker and direct upload mode by default', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/admin/doc-types') return mockDocTypes;
      if (path === '/v1/admin/prototypes') return [];
      return [];
    });
    renderComponent();

    expect(await screen.findByLabelText(/target document type/i)).toBeInTheDocument();
    expect(screen.getByText(/upload sample files directly/i)).toBeInTheDocument();
    expect(screen.getByText(/in-memory training guarantee/i)).toBeInTheDocument();
  });

  it('trains prototype vector via direct file upload with FormData', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/admin/doc-types') return mockDocTypes;
      if (path === '/v1/admin/prototypes') return [];
      return [];
    });
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      doc_type_id: 'dt-00000000-0000-0000-0000-000000000001',
      sample_count: 5,
      dimension: 384,
    });

    renderComponent();

    const user = userEvent.setup();
    const docTypeSelect = await screen.findByLabelText(/target document type/i);
    await user.selectOptions(docTypeSelect, 'dt-00000000-0000-0000-0000-000000000001');

    const fileInput = screen.getByLabelText(/upload sample documents/i);
    const files = [
      new File(['content 1'], 'file1.txt', { type: 'text/plain' }),
      new File(['content 2'], 'file2.txt', { type: 'text/plain' }),
      new File(['content 3'], 'file3.txt', { type: 'text/plain' }),
      new File(['content 4'], 'file4.txt', { type: 'text/plain' }),
      new File(['content 5'], 'file5.txt', { type: 'text/plain' }),
    ];

    fireEvent.change(fileInput, { target: { files } });

    expect(screen.getByText('5 / 5–10 files')).toBeInTheDocument();
    expect(screen.getByText('file1.txt')).toBeInTheDocument();

    const trainButton = screen.getByRole('button', { name: /train from uploaded files/i });
    expect(trainButton).toBeEnabled();

    fireEvent.click(trainButton);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalled();
      const callArgs = postSpy.mock.calls[0];
      expect(callArgs[0]).toBe(
        '/v1/admin/doc-types/dt-00000000-0000-0000-0000-000000000001/prototype-upload'
      );
      expect(callArgs[1]).toBeInstanceOf(FormData);
    });

    expect(await screen.findByText(/prototype trained successfully/i)).toBeInTheDocument();
  });

  it('allows training from repository documents mode', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/admin/doc-types') return mockDocTypes;
      if (path === '/v1/admin/prototypes') return [];
      if (path.startsWith('/v1/documents')) return mockDocsPage;
      return [];
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      doc_type_id: 'dt-00000000-0000-0000-0000-000000000001',
      sample_count: 5,
      dimension: 384,
    });

    renderComponent();

    const user = userEvent.setup();
    const docTypeSelect = await screen.findByLabelText(/target document type/i);
    await user.selectOptions(docTypeSelect, 'dt-00000000-0000-0000-0000-000000000001');

    const repoTab = screen.getByRole('button', { name: /select from ingested repository/i });
    fireEvent.click(repoTab);

    expect(await screen.findByText('sample_1.pdf')).toBeInTheDocument();

    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBe(5);

    checkboxes.forEach((cb) => fireEvent.click(cb));

    const trainButton = screen.getByRole('button', { name: /train from repository samples/i });
    expect(trainButton).toBeEnabled();

    fireEvent.click(trainButton);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        '/v1/admin/doc-types/dt-00000000-0000-0000-0000-000000000001/prototype',
        {
          document_ids: [
            'doc-00000000-0000-0000-0000-000000000001',
            'doc-00000000-0000-0000-0000-000000000002',
            'doc-00000000-0000-0000-0000-000000000003',
            'doc-00000000-0000-0000-0000-000000000004',
            'doc-00000000-0000-0000-0000-000000000005',
          ],
        }
      );
    });
  });

  it('allows resetting single prototype and all prototypes', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/v1/admin/doc-types') return mockDocTypes;
      if (path === '/v1/admin/prototypes') return mockPrototypes;
      return [];
    });

    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValue({});
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderComponent();

    // Verify Active Trained Prototypes table lists Vendor MSA
    expect(await screen.findByText('Active Trained Prototypes (1)')).toBeInTheDocument();
    expect(screen.getByText('5 samples')).toBeInTheDocument();

    // Click Reset Effect on table
    const resetTableBtn = screen.getByRole('button', { name: /reset effect/i });
    fireEvent.click(resetTableBtn);

    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith(
        '/v1/admin/doc-types/dt-00000000-0000-0000-0000-000000000001/prototype'
      );
    });

    // Click Reset All Prototypes button
    const resetAllBtn = screen.getByRole('button', { name: /reset all prototypes/i });
    fireEvent.click(resetAllBtn);

    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith('/v1/admin/prototypes');
    });
  });
});
