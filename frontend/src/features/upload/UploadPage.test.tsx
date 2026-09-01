import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UploadPage } from './UploadPage';
import { setAuthToken } from '../../api/client';
import {
  renderWithProviders,
  jsonResponse,
  problemResponse,
  PERSONA_EMPLOYEE,
} from '../../test-utils';

const PRESIGNED_URL = 'https://storage.internal:9000/docs-quarantine/abc123?X-Amz-Signature=deadbeef';

const fetchMock = vi.fn();

/** Records every PUT the page makes straight to object storage. */
class RecordingXhr {
  static instances: RecordingXhr[] = [];
  /** Status the fake storage endpoint answers with. */
  static nextStatus = 200;
  method = '';
  url = '';
  headers: Record<string, string> = {};
  withCredentials = true;
  body: unknown = null;
  status = 200;
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    RecordingXhr.instances.push(this);
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  send(body: unknown) {
    this.body = body;
    // Resolve on the next tick, the way a real upload completes asynchronously.
    queueMicrotask(() => {
      this.status = RecordingXhr.nextStatus;
      if (this.status < 300) {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 10, total: 10 } as ProgressEvent);
      }
      this.onload?.();
    });
  }
}

function pdfFile(name = 'contract.pdf', type = 'application/pdf') {
  return new File(['%PDF-1.7 fake bytes'], name, { type });
}

/** JSON bodies the page sent to the API, parsed. */
function apiJsonBodies(): unknown[] {
  return fetchMock.mock.calls
    .map((call) => (call[1] as RequestInit | undefined)?.body)
    .filter((b): b is string => typeof b === 'string')
    .map((b) => JSON.parse(b));
}

beforeEach(() => {
  localStorage.clear();
  setAuthToken('token-abc');
  fetchMock.mockReset();
  RecordingXhr.instances = [];
  RecordingXhr.nextStatus = 200;
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('XMLHttpRequest', RecordingXhr as unknown as typeof XMLHttpRequest);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, file = pdfFile()) {
  await user.upload(screen.getByLabelText(/document file/i), file);
  await user.click(screen.getByRole('button', { name: /start upload/i }));
}

describe('UploadPage — invariant #1: the API never touches the bytes', () => {
  it('sends the file body ONLY to the presigned URL, never to the API', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === '/v1/uploads') {
        return Promise.resolve(
          jsonResponse({
            upload_id: 'up-1',
            presigned_put: { url: PRESIGNED_URL, fields: {}, expires_at: '2026-08-28T00:01:30Z' },
          })
        );
      }
      if (url === '/v1/uploads/up-1/complete') {
        return Promise.resolve(
          jsonResponse({ document_id: 'doc-1', version_id: 'ver-1', status: 'processing' })
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />, { persona: PERSONA_EMPLOYEE });

    const file = pdfFile();
    await fillAndSubmit(user, file);

    await waitFor(() => expect(screen.getByText(/upload complete/i)).toBeInTheDocument());

    // 1. The bytes went to the presigned storage URL, via XHR, exactly once.
    expect(RecordingXhr.instances).toHaveLength(1);
    const put = RecordingXhr.instances[0];
    expect(put.method).toBe('PUT');
    expect(put.url).toBe(PRESIGNED_URL);
    expect(put.body).toBe(file);

    // 2. Nothing that reached the API carried the file. Every API body is a
    //    small JSON envelope; none is a File/Blob/FormData/ArrayBuffer. If
    //    someone ever routes the body through `api.post`, this fails.
    for (const [, init] of fetchMock.mock.calls) {
      const body = (init as RequestInit | undefined)?.body;
      expect(body instanceof File).toBe(false);
      expect(body instanceof Blob).toBe(false);
      expect(body instanceof FormData).toBe(false);
      expect(body instanceof ArrayBuffer).toBe(false);
      if (typeof body === 'string') {
        expect(body).not.toContain('%PDF');
      }
    }

    // 3. Every API call was same-origin; the presigned host was never fetched.
    for (const [url] of fetchMock.mock.calls) {
      expect(String(url).startsWith('/v1/')).toBe(true);
    }

    // 4. The presigned PUT carried no session credential (the URL is the credential).
    expect(Object.keys(put.headers).map((k) => k.toLowerCase())).not.toContain('authorization');
    expect(put.withCredentials).toBe(false);
  });

  it('follows the intent -> PUT -> complete order', async () => {
    const order: string[] = [];
    fetchMock.mockImplementation((url: string) => {
      order.push(`fetch:${url}`);
      if (url === '/v1/uploads') {
        return Promise.resolve(
          jsonResponse({
            upload_id: 'up-1',
            presigned_put: { url: PRESIGNED_URL, fields: {}, expires_at: 'x' },
          })
        );
      }
      return Promise.resolve(jsonResponse({ document_id: 'd', version_id: 'v', status: 'ok' }));
    });

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    await fillAndSubmit(user);
    await waitFor(() => expect(screen.getByText(/upload complete/i)).toBeInTheDocument());

    expect(order).toEqual(['fetch:/v1/uploads', 'fetch:/v1/uploads/up-1/complete']);
    // The PUT is sandwiched between them: `complete` is only called after the
    // storage write resolved.
    expect(RecordingXhr.instances).toHaveLength(1);
  });

  it('declares the SAME content type in the intent and in the PUT', async () => {
    // MinIO/S3 sign Content-Type into the presigned URL, so a mismatch is a 403,
    // not a metadata nit. This previously said 'application/pdf' in the intent
    // and 'application/octet-stream' in the PUT for any file the browser could
    // not type.
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url === '/v1/uploads'
          ? jsonResponse({ upload_id: 'up-1', presigned_put: { url: PRESIGNED_URL, fields: {}, expires_at: 'x' } })
          : jsonResponse({ document_id: 'd', version_id: 'v', status: 'ok' })
      )
    );

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    // A file the browser cannot type (empty MIME) — the exact case that used to
    // diverge between the intent and the PUT.
    await fillAndSubmit(user, new File(['bytes'], 'mystery.pdf', { type: '' }));
    await waitFor(() => expect(screen.getByText(/upload complete/i)).toBeInTheDocument());

    const intent = apiJsonBodies()[0] as { content_type: string };
    expect(intent.content_type).toBe('application/octet-stream');
    expect(RecordingXhr.instances[0].headers['Content-Type']).toBe(intent.content_type);
  });

  it('sends the intent fields the API actually requires', async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url === '/v1/uploads'
          ? jsonResponse({ upload_id: 'up-1', presigned_put: { url: PRESIGNED_URL, fields: {}, expires_at: 'x' } })
          : jsonResponse({ document_id: 'd', version_id: 'v', status: 'ok' })
      )
    );

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    await fillAndSubmit(user, pdfFile('msa.pdf'));
    await waitFor(() => expect(screen.getByText(/upload complete/i)).toBeInTheDocument());

    const intent = apiJsonBodies()[0] as Record<string, unknown>;
    expect(Object.keys(intent).sort()).toEqual(['content_type', 'filename', 'size_bytes']);
    expect(intent.filename).toBe('msa.pdf');
    expect(typeof intent.size_bytes).toBe('number');
  });
});

describe('UploadPage — failure handling', () => {
  it('surfaces an RFC 7807 problem from the intent request and sends no bytes', async () => {
    fetchMock.mockResolvedValue(
      problemResponse(403, { title: 'Forbidden', detail: 'You may not upload to that department.' })
    );

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />, { persona: PERSONA_EMPLOYEE });
    await fillAndSubmit(user);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('You may not upload to that department.')
    );
    expect(screen.getByRole('alert')).toHaveTextContent('HTTP 403');

    // Nothing was written to storage.
    expect(RecordingXhr.instances).toHaveLength(0);
    // And the form is usable again rather than stuck mid-flight.
    expect(screen.getByRole('button', { name: /start upload/i })).toBeEnabled();
  });

  it('surfaces a storage failure and does NOT call complete', async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url === '/v1/uploads'
          ? jsonResponse({ upload_id: 'up-1', presigned_put: { url: PRESIGNED_URL, fields: {}, expires_at: 'x' } })
          : jsonResponse({ document_id: 'd', version_id: 'v', status: 'ok' })
      )
    );
    // Make the storage PUT fail with a signature error.
    RecordingXhr.nextStatus = 403;

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    await fillAndSubmit(user);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/Storage upload failed with status 403/)
    );
    // A quarantine object that never landed must not be marked complete.
    expect(fetchMock.mock.calls.map(([u]) => u)).toEqual(['/v1/uploads']);
  });

  it('refuses to send bytes when the intent response has no presigned URL', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ upload_id: 'up-1' }));

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    await fillAndSubmit(user);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/refusing to send bytes/i)
    );
    expect(RecordingXhr.instances).toHaveLength(0);
  });

  it('rejects an oversized file before any request is made', async () => {
    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);

    const huge = new File(['x'], 'huge.pdf', { type: 'application/pdf' });
    Object.defineProperty(huge, 'size', { value: 200 * 1024 * 1024 });
    await user.upload(screen.getByLabelText(/document file/i), huge);

    expect(screen.getByRole('alert')).toHaveTextContent(/File too large/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(RecordingXhr.instances).toHaveLength(0);
  });
});

  describe('UploadPage — form requirements', () => {
    it('allows text files', () => {
      renderWithProviders(<UploadPage />);
      const input = screen.getByLabelText(/document file/i) as HTMLInputElement;
      expect(input.accept).toContain('.txt');
    });

    it('does not render a Department selector', () => {
      renderWithProviders(<UploadPage />);
      expect(screen.queryByLabelText(/target department/i)).toBeNull();
    });
  });

describe('UploadPage — form accessibility', () => {
  it('associates every control with a label', () => {
    renderWithProviders(<UploadPage />);

    expect(screen.getByLabelText(/document title/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/document file/i)).toBeInTheDocument();
  });

  it('exposes upload progress to assistive technology', async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url === '/v1/uploads'
          ? jsonResponse({ upload_id: 'up-1', presigned_put: { url: PRESIGNED_URL, fields: {}, expires_at: 'x' } })
          : jsonResponse({ document_id: 'd', version_id: 'v', status: 'ok' })
      )
    );

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    await fillAndSubmit(user);

    await waitFor(() => expect(screen.getByRole('progressbar')).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    );
  });
});

describe('UploadPage — bulk upload', () => {
  it('accepts multiple files and lists each with its own row', async () => {
    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    const input = screen.getByTestId('file-input') as HTMLInputElement;
    await user.upload(input, [
      new File(['a'], 'a.pdf', { type: 'application/pdf' }),
      new File(['b'], 'b.pdf', { type: 'application/pdf' }),
    ]);
    expect(await screen.findByText('a.pdf')).toBeInTheDocument();
    expect(await screen.findByText('b.pdf')).toBeInTheDocument();
  });

  it('blocks a batch whose total exceeds 1 GiB before contacting the API', async () => {
    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    const files = Array.from({ length: 15 }, (_, i) => {
      const f = new File(['x'], `doc${i}.pdf`, { type: 'application/pdf' });
      Object.defineProperty(f, 'size', { value: 80 * 1024 * 1024 });
      return f;
    });

    const input = screen.getByTestId('file-input') as HTMLInputElement;
    await user.upload(input, files);
    expect(await screen.findByText(/exceeds/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('one failing file does not abort the rest of the batch and reports a partial-success summary', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === '/v1/uploads/batch') {
        return Promise.resolve(
          jsonResponse({
            batch_id: 'batch-1',
            uploads: [
              { upload_id: 'up-1', presigned_put: { url: 'https://storage/a', fields: {}, expires_at: 'x' } },
              { upload_id: 'up-2', presigned_put: { url: 'https://storage/b', fields: {}, expires_at: 'x' } },
            ],
          })
        );
      }
      if (url === '/v1/uploads/up-1/complete') {
        return Promise.resolve(jsonResponse({ document_id: 'd-1', version_id: 'v-1', status: 'ready' }));
      }
      if (url === '/v1/uploads/up-2/complete') {
        return Promise.reject(new Error('Complete failed'));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<UploadPage />);
    const input = screen.getByTestId('file-input') as HTMLInputElement;
    await user.upload(input, [
      new File(['a'], 'a.pdf', { type: 'application/pdf' }),
      new File(['b'], 'b.pdf', { type: 'application/pdf' }),
    ]);

    await user.click(screen.getByRole('button', { name: /start batch upload/i }));

    expect(await screen.findByTestId('file-status-a.pdf')).toHaveTextContent(/done/i);
    expect(await screen.findByTestId('file-status-b.pdf')).toHaveTextContent(/failed/i);
    expect(await screen.findByText(/1 of 2 uploaded/i)).toBeInTheDocument();
  });
});

