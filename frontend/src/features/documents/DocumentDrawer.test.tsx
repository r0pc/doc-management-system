import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentDrawer } from './DocumentDrawer';
import { getAuthToken } from '../../api/client';
import {
  renderWithProviders,
  jsonResponse,
  problemResponse,
  makeDocument,
  PERSONA_ADMIN,
  PERSONA_VIEWER,
  PERSONA_EMPLOYEE,
} from '../../test-utils';

const DOC_ID = '11111111-1111-1111-1111-111111111111';
const fetchMock = vi.fn();

/** Content responses recorded per level so we can assert on the ONE request. */
function routeApi(level: string, contentResponse?: () => Response) {
  fetchMock.mockImplementation((url: string) => {
    if (url === `/v1/documents/${DOC_ID}`) {
      return Promise.resolve(jsonResponse(makeDocument({ id: DOC_ID, level })));
    }
    if (url === `/v1/documents/${DOC_ID}/jobs`) {
      return Promise.resolve(
        jsonResponse([
          { stage: 'scan_for_malware', state: 'succeeded', attempts: 1, error: null, started_at: null, finished_at: '2026-08-01T10:00:00Z' },
          { stage: 'classify', state: 'succeeded', attempts: 1, error: null, started_at: null, finished_at: '2026-08-01T10:01:00Z' },
        ])
      );
    }
    if (url === `/v1/documents/${DOC_ID}/findings`) {
      return Promise.resolve(
        jsonResponse([
          { entity_type: 'SSN', rule_id: 'ssn-us', page_no: 1, char_start: 120, char_end: 131, score: 0.97 },
        ])
      );
    }
    if (url === `/v1/documents/${DOC_ID}/content`) {
      return Promise.resolve(
        contentResponse
          ? contentResponse()
          : new Response('bytes', {
              status: 200,
              headers: { 'Content-Disposition': 'attachment; filename="quarterly-report.pdf"' },
            })
      );
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

function contentCalls() {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes('/content'));
}

beforeEach(() => {
  localStorage.clear();
  // renderWithProviders seeds a persona-matched JWT; no placeholder here.
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  // jsdom implements neither of these.
  vi.stubGlobal('URL', Object.assign(URL, {
    createObjectURL: vi.fn(() => 'blob:mock'),
    revokeObjectURL: vi.fn(),
  }));
  HTMLAnchorElement.prototype.click = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('DocumentDrawer — invariant #17: split content delivery', () => {
  it('labels Confidential/Restricted documents as API-streamed', async () => {
    routeApi('Confidential');
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    await waitFor(() =>
      expect(screen.getByTestId('delivery-mode')).toHaveTextContent('API Stream (Range)')
    );
  });

  it('labels Public/Internal documents as presigned 303', async () => {
    routeApi('Public');
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    await waitFor(() =>
      expect(screen.getByTestId('delivery-mode')).toHaveTextContent('Presigned 303')
    );
  });

  it('treats an unclassified document as Internal, never Public', async () => {
    // Invariant #9: nothing matched floors at Internal.
    routeApi('');
    fetchMock.mockImplementation((url: string) =>
      url === `/v1/documents/${DOC_ID}`
        ? Promise.resolve(jsonResponse(makeDocument({ id: DOC_ID, level: null })))
        : Promise.resolve(jsonResponse([]))
    );
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('delivery-mode')).toBeInTheDocument());
    // The badge falls back to Internal rather than Public.
    expect(screen.getByText('Internal')).toBeInTheDocument();
  });

  it.each(['Restricted', 'Confidential', 'Internal', 'Public'])(
    'downloads %s through the API content endpoint and nowhere else',
    async (level) => {
      // Whatever the level, the client knows exactly ONE URL. It cannot route a
      // Restricted document at a presigned URL because it has none, and it
      // cannot skip the API's authorization + audit for any level.
      routeApi(level);
      const user = userEvent.setup();
      renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />, {
        persona: PERSONA_ADMIN,
      });

      await waitFor(() => expect(screen.getByRole('button', { name: /download/i })).toBeEnabled());
      await user.click(screen.getByRole('button', { name: /download/i }));

      await waitFor(() => expect(contentCalls()).toHaveLength(1));

      const [url, init] = contentCalls()[0];
      expect(url).toBe(`/v1/documents/${DOC_ID}/content`);

      // Same-origin API path only — never a storage host built client-side.
      expect(String(url).startsWith('/v1/')).toBe(true);
      expect((init as RequestInit).headers).toMatchObject({
        // The session credential itself - not a token minted per request.
        Authorization: `Bearer ${getAuthToken()}`,
      });

      // No second request to any other origin followed.
      const foreign = fetchMock.mock.calls.filter(([u]) => !String(u).startsWith('/v1/'));
      expect(foreign).toHaveLength(0);
    }
  );

  it('uses the server-supplied filename from Content-Disposition', async () => {
    routeApi(
      'Confidential',
      () =>
        new Response('bytes', {
          status: 200,
          headers: { 'Content-Disposition': 'attachment; filename="Q3-board-minutes.pdf"' },
        })
    );
    const createAnchor = vi.spyOn(document, 'createElement');

    const user = userEvent.setup();
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByRole('button', { name: /download/i })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: /download/i }));

    await waitFor(() => expect(contentCalls()).toHaveLength(1));
    const anchor = createAnchor.mock.results
      .map((r) => r.value as HTMLElement)
      .find((el): el is HTMLAnchorElement => el instanceof HTMLAnchorElement);
    expect(anchor?.download).toBe('Q3-board-minutes.pdf');
  });

  it('surfaces a denial from the content endpoint instead of failing silently', async () => {
    routeApi('Restricted', () =>
      problemResponse(403, {
        title: 'Forbidden',
        detail: 'Your clearance does not permit downloading this document.',
      })
    );

    const user = userEvent.setup();
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByRole('button', { name: /download/i })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: /download/i }));

    await waitFor(() =>
      expect(
        screen.getByText('Your clearance does not permit downloading this document.')
      ).toBeInTheDocument()
    );
    // And the button recovers rather than staying stuck on "Downloading...".
    expect(screen.getByRole('button', { name: /download/i })).toBeEnabled();
  });
});

describe('DocumentDrawer — invariant #18: preview and download are separate permissions', () => {
  it('hides the download control from a viewer, who has PREVIEW but not DOWNLOAD', async () => {
    routeApi('Public');
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />, {
      persona: PERSONA_VIEWER,
    });

    await waitFor(() => expect(screen.getByText('quarterly-report.pdf')).toBeInTheDocument());

    // The viewer role grants PREVIEW but NOT DOWNLOAD, so the byte-fetching
    // control must not be drawn. This is chrome only: the API re-authorizes
    // DOWNLOAD on every content request (invariant #33).
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
  });

  it('shows the download control to an employee, who has DOWNLOAD', async () => {
    routeApi('Public');
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />, {
      persona: PERSONA_EMPLOYEE,
    });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /download/i })).toBeInTheDocument()
    );
  });

  it('hides the download control when the document outranks the user clearance', async () => {
    // Employee clearance 2 vs a Restricted (rank 4) document. Cosmetic: the
    // server would refuse anyway, and this test must not be read as enforcement.
    routeApi('Restricted');
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />, {
      persona: PERSONA_EMPLOYEE,
    });

    await waitFor(() => expect(screen.getByText('quarterly-report.pdf')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
  });

  it('hides reclassify from a role without RECLASSIFY', async () => {
    routeApi('Internal');
    renderWithProviders(
      <DocumentDrawer documentId={DOC_ID} onClose={() => {}} onReclassify={() => {}} />,
      { persona: PERSONA_EMPLOYEE }
    );

    await waitFor(() => expect(screen.getByText('quarterly-report.pdf')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /reclassify/i })).not.toBeInTheDocument();
  });
});

describe('DocumentDrawer — invariant #12: findings carry offsets, not text', () => {
  it('renders character offsets and never any matched text field', async () => {
    routeApi('Confidential');
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('SSN')).toBeInTheDocument());
    expect(screen.getByText(/Chars \[120\.\.131\]/)).toBeInTheDocument();
  });
});

describe('DocumentDrawer — loading, error and empty states', () => {
  it('renders an error alert, not a blank panel, when the document fetch fails', async () => {
    fetchMock.mockResolvedValue(
      problemResponse(404, { title: 'Not Found', detail: 'No such document in your scope.' })
    );

    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('No such document in your scope.')
    );
    // The footer, which depends on `doc`, must not render alongside the error.
    expect(screen.queryByTestId('delivery-mode')).not.toBeInTheDocument();
  });

  it('renders nothing at all when no document is selected', () => {
    const { container } = renderWithProviders(
      <DocumentDrawer documentId={null} onClose={() => {}} />
    );
    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('renders empty-state copy when there are no findings or jobs', async () => {
    fetchMock.mockImplementation((url: string) =>
      url === `/v1/documents/${DOC_ID}`
        ? Promise.resolve(jsonResponse(makeDocument({ id: DOC_ID })))
        : Promise.resolve(jsonResponse([]))
    );

    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    await waitFor(() =>
      expect(screen.getByText(/No PII or sensitive patterns detected/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/No pipeline stages recorded yet/i)).toBeInTheDocument();
  });
});

describe('DocumentDrawer — accessibility', () => {
  it('exposes a named close button and closes on Escape', async () => {
    routeApi('Internal');
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={onClose} />);

    // The icon-only close button used to have no accessible name at all.
    const close = screen.getByRole('button', { name: /close document inspector/i });
    expect(close).toBeInTheDocument();

    await user.click(close);
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('is a labelled modal dialog and moves focus into itself on open', async () => {
    routeApi('Internal');
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(within(dialog).getByText('Document Inspector')).toBeInTheDocument();

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole('button', { name: /close document inspector/i })
      )
    );
  });
});
describe('DocumentDrawer — failure visibility', () => {
  it('renders the journal error reason for a failed stage', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === `/v1/documents/${DOC_ID}`) return Promise.resolve(jsonResponse(makeDocument({ id: DOC_ID, level: 'Internal' })));
      if (url === `/v1/documents/${DOC_ID}/jobs`) return Promise.resolve(jsonResponse([
        { stage: 'scan', state: 'succeeded', error: null, attempts: 1, started_at: '2026-08-31T10:00:00Z', finished_at: '2026-08-31T10:00:01Z' },
        { stage: 'extract', state: 'failed', error: 'unsupported or malformed content', attempts: 1, started_at: '2026-08-31T10:00:01Z', finished_at: '2026-08-31T10:00:02Z' },
      ]));
      if (url === `/v1/documents/${DOC_ID}/findings`) return Promise.resolve(jsonResponse([]));
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });

    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);
    expect(await screen.findByText('unsupported or malformed content')).toBeInTheDocument();
  });

  it('shows the attempt count when a stage was retried', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === `/v1/documents/${DOC_ID}`) return Promise.resolve(jsonResponse(makeDocument({ id: DOC_ID, level: 'Internal' })));
      if (url === `/v1/documents/${DOC_ID}/jobs`) return Promise.resolve(jsonResponse([
        { stage: 'scan', state: 'failed', error: 'transient failure in scan; retries exhausted', attempts: 3, started_at: '2026-08-31T10:00:00Z', finished_at: '2026-08-31T10:00:05Z' }
      ]));
      if (url === `/v1/documents/${DOC_ID}/findings`) return Promise.resolve(jsonResponse([]));
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });

    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);
    expect(await screen.findByText(/3 attempts/i)).toBeInTheDocument();
  });

  it('does not render an error row for a clean journal', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === `/v1/documents/${DOC_ID}`) return Promise.resolve(jsonResponse(makeDocument({ id: DOC_ID, level: 'Internal' })));
      if (url === `/v1/documents/${DOC_ID}/jobs`) return Promise.resolve(jsonResponse([
        { stage: 'scan', state: 'succeeded', error: null, attempts: 1, started_at: '2026-08-31T10:00:00Z', finished_at: '2026-08-31T10:00:01Z' }
      ]));
      if (url === `/v1/documents/${DOC_ID}/findings`) return Promise.resolve(jsonResponse([]));
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });

    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText('scan')).toBeInTheDocument());
    expect(screen.queryByTestId('job-error')).not.toBeInTheDocument();
  });
});

describe('DocumentDrawer — classifier engine attribution', () => {
  const previewFor = (decided_by: string, confidence: number, doc_type: string | null) => ({
    id: DOC_ID,
    filename: 'monthly_report_5.pdf',
    mime: 'application/pdf',
    char_count: 10,
    pages: [],
    full_text: '',
    justification: {
      level: 'Confidential',
      level_rank: 3,
      level_reason: 'Confidential: matched',
      doc_type,
      decided_by,
      confidence,
      confidence_threshold: 0.85,
      keywords: [],
      findings: [],
    },
  });

  const mount = (decided_by: string, confidence: number, doc_type: string | null) => {
    fetchMock.mockImplementation((url: string) => {
      if (url === `/v1/documents/${DOC_ID}`)
        return Promise.resolve(jsonResponse(makeDocument({ id: DOC_ID, level: 'Confidential', doc_type })));
      if (url === `/v1/documents/${DOC_ID}/preview`)
        return Promise.resolve(jsonResponse(previewFor(decided_by, confidence, doc_type)));
      if (url === `/v1/documents/${DOC_ID}/jobs`) return Promise.resolve(jsonResponse([]));
      if (url === `/v1/documents/${DOC_ID}/findings`) return Promise.resolve(jsonResponse([]));
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    renderWithProviders(<DocumentDrawer documentId={DOC_ID} onClose={() => {}} />);
  };

  it('never shows a 0.0% confidence for a prototype match', async () => {
    // decided_by='rules' WITH a doc_type is a prototype hit. Its confidence is
    // 0.0 by design (#11 forbids storing a cosine there), so rendering it as a
    // percentage claims the opposite of what happened.
    mount('rules', 0.0, 'Monthly Report');
    const engine = await screen.findByTestId('classifier-engine');
    expect(engine.textContent).not.toMatch(/0\.0%/);
  });

  it('labels a prototype match as such rather than as RULES', async () => {
    mount('rules', 0.0, 'Monthly Report');
    const engine = await screen.findByTestId('classifier-engine');
    expect(engine.textContent).toMatch(/prototype/i);
  });

  it('shows plain RULES with no percentage when nothing decided a type', async () => {
    mount('rules', 0.0, null);
    const engine = await screen.findByTestId('classifier-engine');
    expect(engine.textContent).toMatch(/rules/i);
    expect(engine.textContent).not.toMatch(/%/);
  });

  it('still shows the calibrated percentage for an ML decision', async () => {
    mount('ml', 0.9640539, 'Monthly Report');
    const engine = await screen.findByTestId('classifier-engine');
    expect(engine.textContent).toMatch(/96\.4%/);
  });

  it('shows no percentage for a human decision', async () => {
    mount('human', 0.0, 'Monthly Report');
    const engine = await screen.findByTestId('classifier-engine');
    expect(engine.textContent).not.toMatch(/%/);
  });
});
