import React, { useState, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { UploadIntentResponse, BatchUploadResponse } from '../../api/types';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { DepartmentPicker } from '../departments/DepartmentPicker';
import { useDepartments, withRoot } from '../departments/useDepartments';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { UploadCloud, CheckCircle2, FileText, AlertCircle } from 'lucide-react';
import { formatBytes } from '../../lib/utils';

export interface FileUploadItem {
  id: string;
  file: File;
  title: string;
  status: 'idle' | 'intent' | 'uploading' | 'completing' | 'done' | 'failed';
  progress: number;
  error?: string;
  abortController?: AbortController;
}

const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MiB
const MAX_BATCH_SIZE = 1024 * 1024 * 1024; // 1 GiB
const MAX_BATCH_FILES = 500;

export const UploadPage: React.FC = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [files, setFiles] = useState<FileUploadItem[]>([]);
  const [title, setTitle] = useState('');
  const [uploadStage, setUploadStage] = useState<'idle' | 'intent' | 'uploading' | 'completing' | 'done'>('idle');
  const [error, setError] = useState<unknown>(null);
  // Departments the uploaded documents should belong to. The tenant root is
  // added by the server regardless, so this holds only the extra choices.
  const [departmentSelection, setDepartmentSelection] = useState<Set<string>>(new Set());
  const { data: departments } = useDepartments();
  const [summary, setSummary] = useState<string | null>(null);

  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const batchAbortController = useRef<AbortController | null>(null);

  React.useEffect(
    () => () => {
      if (redirectTimer.current !== null) clearTimeout(redirectTimer.current);
    },
    []
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;

    const selectedFiles = Array.from(e.target.files);

    if (selectedFiles.length > MAX_BATCH_FILES) {
      setError(new Error(`Batch exceeds ${MAX_BATCH_FILES} files.`));
      return;
    }

    for (const f of selectedFiles) {
      if (f.size > MAX_FILE_SIZE) {
        setError(new Error(`File too large. File exceeds 100 MB limit (${formatBytes(f.size)} selected).`));
        return;
      }
    }

    const totalSize = selectedFiles.reduce((acc, f) => acc + f.size, 0);
    if (totalSize > MAX_BATCH_SIZE) {
      setError(new Error(`Batch exceeds 1 GiB total size limit (${formatBytes(totalSize)} selected).`));
      return;
    }

    const items: FileUploadItem[] = selectedFiles.map((file, idx) => ({
      id: `${file.name}-${file.size}-${idx}-${Date.now()}`,
      file,
      title: file.name,
      status: 'idle',
      progress: 0,
    }));

    setFiles(items);
    if (items.length === 1 && !title) {
      setTitle(items[0].file.name);
    }
    setError(null);
    setSummary(null);
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) {
      setError(new Error('Please select a document to upload'));
      return;
    }

    const totalSize = files.reduce((acc, f) => acc + f.file.size, 0);
    if (totalSize > MAX_BATCH_SIZE) {
      setError(new Error(`Batch exceeds 1 GiB total size limit (${formatBytes(totalSize)} selected).`));
      return;
    }

    for (const f of files) {
      if (f.file.size > MAX_FILE_SIZE) {
        setError(new Error(`File ${f.file.name} exceeds 100 MB per-file limit.`));
        return;
      }
    }

    try {
      setError(null);
      setSummary(null);
      batchAbortController.current = new AbortController();

      // Single file upload path
      if (files.length === 1) {
        const item = files[0];
        const contentType = item.file.type || 'application/octet-stream';

        let uploadFilename = title.trim() || item.file.name;
        const fileExt = item.file.name.includes('.') ? item.file.name.slice(item.file.name.lastIndexOf('.')) : '';
        if (fileExt && !uploadFilename.toLowerCase().endsWith(fileExt.toLowerCase())) {
          uploadFilename = `${uploadFilename}${fileExt}`;
        }

        setUploadStage('intent');
        setFiles((prev) =>
          prev.map((f) => (f.id === item.id ? { ...f, status: 'intent', progress: 10 } : f))
        );

        const intent = await api.post<UploadIntentResponse>('/v1/uploads', {
          filename: uploadFilename,
          size_bytes: item.file.size,
          content_type: contentType,
          department_ids: withRoot(departmentSelection, departments),
        });

        if (!intent?.presigned_put?.url) {
          throw new Error('Upload intent did not return a presigned URL; refusing to send bytes.');
        }

        setUploadStage('uploading');
        setFiles((prev) =>
          prev.map((f) => (f.id === item.id ? { ...f, status: 'uploading', progress: 30 } : f))
        );

        await api.putDirect(
          intent.presigned_put.url,
          item.file,
          contentType,
          intent.presigned_put.fields,
          (percent) => {
            setFiles((prev) =>
              prev.map((f) => (f.id === item.id ? { ...f, progress: 30 + Math.floor(percent * 0.6) } : f))
            );
          },
          batchAbortController.current.signal
        );

        setUploadStage('completing');
        setFiles((prev) =>
          prev.map((f) => (f.id === item.id ? { ...f, status: 'completing', progress: 90 } : f))
        );

        await api.post(`/v1/uploads/${intent.upload_id}/complete`, {
          size_bytes: item.file.size,
        });

        setFiles((prev) =>
          prev.map((f) => (f.id === item.id ? { ...f, status: 'done', progress: 100 } : f))
        );
        setUploadStage('done');
        setSummary('1 of 1 uploaded');

        queryClient.invalidateQueries({ queryKey: ['documents'] });
        queryClient.invalidateQueries({ queryKey: ['review'] });

        redirectTimer.current = setTimeout(() => {
          navigate('/documents');
        }, 1200);
        return;
      }

      // Multi-file batch upload path
      setUploadStage('intent');
      const batchPayload = {
        files: files.map((f) => ({
          filename: f.file.name,
          size_bytes: f.file.size,
          content_type: f.file.type || 'application/octet-stream',
        })),
        department_ids: withRoot(departmentSelection, departments),
      };

      const batchResponse = await api.post<BatchUploadResponse>('/v1/uploads/batch', batchPayload);

      if (!batchResponse?.uploads || batchResponse.uploads.length !== files.length) {
        throw new Error('Batch upload intent failed to return all presigned URLs.');
      }

      setUploadStage('uploading');

      // Upload files with bounded concurrency of 3
      const CONCURRENCY = 3;
      let currentIndex = 0;
      let completedCount = 0;
      let failedCount = 0;

      const uploadWorker = async (): Promise<void> => {
        while (currentIndex < files.length) {
          const index = currentIndex++;
          const currentItem = files[index];
          const intent = batchResponse.uploads[index];
          const contentType = currentItem.file.type || 'application/octet-stream';

          try {
            setFiles((prev) =>
              prev.map((f, i) => (i === index ? { ...f, status: 'uploading', progress: 20 } : f))
            );

            await api.putDirect(
              intent.presigned_put.url,
              currentItem.file,
              contentType,
              intent.presigned_put.fields,
              (percent) => {
                setFiles((prev) =>
                  prev.map((f, i) =>
                    i === index ? { ...f, progress: 20 + Math.floor(percent * 0.7) } : f
                  )
                );
              },
              batchAbortController.current?.signal
            );

            setFiles((prev) =>
              prev.map((f, i) => (i === index ? { ...f, status: 'completing', progress: 95 } : f))
            );

            await api.post(`/v1/uploads/${intent.upload_id}/complete`, {
              size_bytes: currentItem.file.size,
            });

            setFiles((prev) =>
              prev.map((f, i) => (i === index ? { ...f, status: 'done', progress: 100 } : f))
            );
            completedCount++;
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : 'Upload failed';
            setFiles((prev) =>
              prev.map((f, i) => (i === index ? { ...f, status: 'failed', error: msg } : f))
            );
            failedCount++;
          }
        }
      };

      const workers = Array.from({ length: Math.min(CONCURRENCY, files.length) }, () => uploadWorker());
      await Promise.all(workers);

      setUploadStage('done');
      const totalUploaded = completedCount;
      const totalCount = files.length;
      setSummary(`${totalUploaded} of ${totalCount} uploaded`);

      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['review'] });

      if (failedCount === 0) {
        redirectTimer.current = setTimeout(() => {
          navigate('/documents');
        }, 1200);
      }
    } catch (err: unknown) {
      setUploadStage('idle');
      setError(err);
    }
  };

  const handleCancel = () => {
    if (batchAbortController.current) {
      batchAbortController.current.abort();
    }
    setUploadStage('idle');
  };

  const overallProgress =
    files.length > 0
      ? Math.round(files.reduce((acc, f) => acc + (f.status === 'done' ? 100 : f.progress), 0) / files.length)
      : 0;

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <div className="pb-3 border-b border-[#d0d7de] dark:border-[#30363d]">
        <h2 className="text-lg font-bold text-[#1f2328] dark:text-[#e6edf3] tracking-tight">Upload Document</h2>
        <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-0.5">
          Documents are quarantined, scanned for malware with ClamAV, and classified asynchronously.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ingestion Intent & Direct Quarantine PUT</CardTitle>
          <CardDescription>
            Zero-broker upload (Invariant #1): API never touches raw bytes on the write path.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleUpload} className="space-y-4">
            {files.length <= 1 && (
              <div>
                <label
                  htmlFor="upload-title"
                  className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
                >
                  Document Title
                </label>
                <Input
                  id="upload-title"
                  type="text"
                  placeholder="e.g. Master Services Agreement 2026"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={uploadStage !== 'idle'}
                />
              </div>
            )}

            <div>
              <span className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                Departments
              </span>
              <p className="text-[11px] text-[#656d76] dark:text-[#848d97] mb-1.5">
                Who will be able to see this, subject to their clearance. Applies
                to every file in this upload.
              </p>
              <DepartmentPicker
                selected={departmentSelection}
                onChange={setDepartmentSelection}
                disabled={uploadStage !== 'idle'}
              />
            </div>

            <div>
              <label
                htmlFor="upload-file"
                className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
              >
                Document File (.pdf, .docx, .xlsx, .txt)
              </label>
              <div className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-[#d0d7de] dark:border-[#30363d] border-dashed rounded-md hover:border-[#0969da] dark:hover:border-[#2f81f7] transition-colors bg-[#f6f8fa] dark:bg-[#161b22]">
                <input
                  id="upload-file"
                  data-testid="file-input"
                  type="file"
                  multiple
                  accept=".pdf,.docx,.xlsx,.txt"
                  className="hidden"
                  onChange={handleFileChange}
                  disabled={uploadStage !== 'idle'}
                />
                <div className="text-center w-full">
                  <div className="flex items-center justify-center gap-2 text-xs text-[#0969da] dark:text-[#58a6ff] mb-1">
                    <UploadCloud className="w-5 h-5" />
                    <label
                      htmlFor="upload-file"
                      className="cursor-pointer hover:underline font-semibold"
                    >
                      Select File
                    </label>
                    <p className="pl-1.5 py-0.5 text-[#1f2328] dark:text-[#e6edf3]">or drag and drop</p>
                  </div>
                  <p className="text-[10px] text-[#656d76] dark:text-[#848d97]">
                    PDF, DOCX, XLSX, or TXT up to 100 MiB per file (up to 1 GiB / 500 files total)
                  </p>
                </div>
              </div>
            </div>

            {/* Selected File List */}
            {files.length > 0 && (
              <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                {files.map((item) => (
                  <div
                    key={item.id}
                    className="p-2.5 bg-[#f6f8fa] dark:bg-[#161b22] border border-[#d0d7de] dark:border-[#30363d] rounded-md space-y-1.5 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 text-[#1f2328] dark:text-[#e6edf3] font-medium truncate">
                        <FileText className="w-4 h-4 shrink-0 text-[#656d76] dark:text-[#848d97]" />
                        <span className="truncate">{item.file.name}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0 ml-2">
                        <span className="text-[#656d76] dark:text-[#848d97] font-mono text-[11px]">
                          {formatBytes(item.file.size)}
                        </span>
                        <span
                          data-testid={`file-status-${item.file.name}`}
                          className={`inline-flex items-center px-1.5 py-0.2 rounded-full text-[10px] font-semibold capitalize border ${
                            item.status === 'done'
                              ? 'bg-[#dafbe1] dark:bg-[#238636]/25 text-[#1a7f37] dark:text-[#3fb950] border-[#4ac26b]/40'
                              : item.status === 'failed'
                              ? 'bg-[#ffebe9] dark:bg-[#da3633]/25 text-[#cf222e] dark:text-[#f85149] border-[#ff8182]/40'
                              : item.status === 'uploading' || item.status === 'intent' || item.status === 'completing'
                              ? 'bg-[#ddf4ff] dark:bg-[#388bfd]/25 text-[#0969da] dark:text-[#58a6ff] border-[#54aeff]/40'
                              : 'bg-[#f6f8fa] dark:bg-[#21262d] text-[#656d76] dark:text-[#848d97] border-[#d0d7de] dark:border-[#30363d]'
                          }`}
                        >
                          {item.status}
                        </span>
                      </div>
                    </div>

                    {item.status !== 'idle' && (
                      <div className="w-full bg-[#eaeef2] dark:bg-[#21262d] rounded-full h-1 overflow-hidden">
                        <div
                          className={`h-1 rounded-full transition-all duration-200 ${
                            item.status === 'done'
                              ? 'bg-[#1a7f37] dark:bg-[#3fb950]'
                              : item.status === 'failed'
                              ? 'bg-[#cf222e] dark:bg-[#f85149]'
                              : 'bg-[#0969da] dark:bg-[#2f81f7]'
                          }`}
                          style={{
                            width: `${item.status === 'done' ? 100 : item.progress}%`,
                          }}
                        />
                      </div>
                    )}
                    {item.error && (
                      <p className="text-[11px] text-[#cf222e] dark:text-[#f85149] flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" /> {item.error}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}

            {uploadStage !== 'idle' && (
              <div className="space-y-1.5 pt-2">
                <div className="flex justify-between text-xs text-[#656d76] dark:text-[#848d97]">
                  <span className="font-medium">
                    {uploadStage === 'intent' && 'Requesting upload intent...'}
                    {uploadStage === 'uploading' && `Uploading directly to quarantine (${overallProgress}%)...`}
                    {uploadStage === 'completing' && 'Finalizing upload & queueing pipeline...'}
                    {uploadStage === 'done' && 'Upload complete! Ingesting...'}
                  </span>
                  <span className="font-mono">{overallProgress}%</span>
                </div>
                <div
                  role="progressbar"
                  aria-label="Upload progress"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={uploadStage === 'done' ? 100 : overallProgress}
                  className="w-full bg-[#eaeef2] dark:bg-[#21262d] rounded-full h-1.5 overflow-hidden"
                >
                  <div
                    className={`h-1.5 rounded-full transition-all duration-200 ${
                      uploadStage === 'done' ? 'bg-[#1a7f37] dark:bg-[#3fb950]' : 'bg-[#0969da] dark:bg-[#2f81f7]'
                    }`}
                    style={{
                      width: `${uploadStage === 'done' ? 100 : overallProgress}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {summary && (
              <div className="p-2 bg-[#dafbe1]/40 dark:bg-[#238636]/15 border border-[#4ac26b]/40 rounded-md text-xs font-semibold text-[#1a7f37] dark:text-[#3fb950] flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>{summary}</span>
              </div>
            )}

            <ProblemAlert error={error} />

            <div className="pt-2 flex gap-2">
              {uploadStage === 'uploading' && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleCancel}
                  className="w-full h-8 border-[#cf222e] text-[#cf222e] hover:bg-[#ffebe9] dark:border-[#f85149] dark:text-[#ff7b72] dark:hover:bg-[#490202]"
                >
                  Cancel Upload
                </Button>
              )}
              <Button
                type="submit"
                variant="default"
                disabled={files.length === 0 || uploadStage !== 'idle'}
                className="w-full h-8"
              >
                {uploadStage === 'idle' && (files.length > 1 ? `Start Batch Upload (${files.length} files)` : 'Start Upload')}
                {uploadStage === 'intent' && 'Preparing Intent...'}
                {uploadStage === 'uploading' && 'Uploading Bytes...'}
                {uploadStage === 'completing' && 'Finalizing...'}
                {uploadStage === 'done' && (
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-white" /> Success! Redirecting...
                  </span>
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
