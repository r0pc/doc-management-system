import React, { useState, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { UploadIntentResponse } from '../../api/types';
import { useAuth } from '../../api/auth';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { UploadCloud, CheckCircle2, FileText } from 'lucide-react';
import { formatBytes } from '../../lib/utils';

export const UploadPage: React.FC = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { currentPersona } = useAuth();

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [departmentId, setDepartmentId] = useState(currentPersona?.departmentId || '');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStage, setUploadStage] = useState<'idle' | 'intent' | 'uploading' | 'completing' | 'done'>('idle');
  const [error, setError] = useState<unknown>(null);
  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortController = useRef<AbortController | null>(null);

  // Clear the post-success redirect timer on unmount. Without this, navigating
  // away during the 1.2s success pause fired `navigate()` against an unmounted
  // router.
  React.useEffect(
    () => () => {
      if (redirectTimer.current !== null) clearTimeout(redirectTimer.current);
    },
    []
  );

  // Sync default department when persona switches
  React.useEffect(() => {
    if (currentPersona?.departmentId) {
      setDepartmentId(currentPersona.departmentId);
    }
  }, [currentPersona]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0];
      const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MB
      if (selected.size > MAX_FILE_SIZE) {
        setError(new Error(`File too large. Maximum size is 100 MB, selected file is ${formatBytes(selected.size)}.`));
        return;
      }
      setFile(selected);
      if (!title) {
        setTitle(selected.name);
      }
      setError(null);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError(new Error('Please select a document to upload'));
      return;
    }

    try {
      setError(null);
      setUploadStage('intent');

      // The declared content type must be IDENTICAL in the intent and in the
      // PUT: S3/MinIO signs the Content-Type into the presigned URL, so a
      // mismatch is a signature failure (403), not a metadata nit. Previously
      // the intent said 'application/pdf' and the PUT said
      // 'application/octet-stream' whenever the browser could not sniff a type.
      // The server sniffs the real type on ingest regardless (invariant #19) —
      // this value is a transport declaration, not a trusted classification.
      const contentType = file.type || 'application/octet-stream';

      // Ensure file extension is preserved even if user edited the title
      let uploadFilename = title.trim() || file.name;
      const fileExt = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')) : '';
      if (fileExt && !uploadFilename.toLowerCase().endsWith(fileExt.toLowerCase())) {
        uploadFilename = `${uploadFilename}${fileExt}`;
      }

      // Step 1: Request Upload Intent (Invariant #1)
      const intent = await api.post<UploadIntentResponse>('/v1/uploads', {
        filename: uploadFilename,
        size_bytes: file.size,
        content_type: contentType,
      });

      if (!intent?.presigned_put?.url) {
        throw new Error('Upload intent did not return a presigned URL; refusing to send bytes.');
      }

      // Step 2: Direct browser PUT to presigned quarantine URL (Invariant #1).
      // The file body goes browser -> storage. It never passes through `api.post`
      // and never reaches the API origin.
      setUploadStage('uploading');
      abortController.current = new AbortController();
      await api.putDirect(
        intent.presigned_put.url,
        file,
        contentType,
        intent.presigned_put.fields,
        (percent) => setUploadProgress(percent),
        abortController.current.signal
      );

      // Step 3: Complete upload and enqueue processing chain
      setUploadStage('completing');
      await api.post(`/v1/uploads/${intent.upload_id}/complete`, {
        size_bytes: file.size,
      });

      setUploadStage('done');
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['review'] });

      redirectTimer.current = setTimeout(() => {
        navigate('/documents');
      }, 1200);
    } catch (err: unknown) {
      setUploadStage('idle');
      setUploadProgress(0);
      setError(err);
    }
  };

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
                required
              />
            </div>

            <div>
              <label
                htmlFor="upload-department"
                className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
              >
                Target Department UUID
              </label>
              <Input
                id="upload-department"
                type="text"
                value={departmentId}
                onChange={(e) => setDepartmentId(e.target.value)}
                placeholder="00000000-0000-0000-0000-000000000010"
                required
              />
              <p className="text-[11px] text-[#656d76] dark:text-[#848d97] mt-1">
                Current Persona Department: {currentPersona?.departmentLabel}
              </p>
            </div>

            <div>
              <label
                htmlFor="upload-file"
                className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
              >
                Document File (.pdf, .docx, .xlsx)
              </label>
              <div className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-[#d0d7de] dark:border-[#30363d] border-dashed rounded-md hover:border-[#0969da] dark:hover:border-[#2f81f7] transition-colors bg-[#f6f8fa] dark:bg-[#161b22]">
                <div className="space-y-2 text-center">
                  <UploadCloud className="mx-auto h-7 w-7 text-[#656d76] dark:text-[#848d97]" />
                  <div className="flex text-xs text-[#656d76] dark:text-[#848d97] justify-center">
                    <label className="relative cursor-pointer bg-white dark:bg-[#21262d] rounded font-semibold text-[#0969da] dark:text-[#2f81f7] hover:underline focus-within:outline-none px-2 py-0.5 border border-[#d0d7de] dark:border-[#30363d] shadow-2xs">
                      <span>Choose file</span>
                      <input
                        id="upload-file"
                        type="file"
                        className="sr-only"
                        accept=".pdf,.docx,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        onChange={handleFileChange}
                      />
                    </label>
                    <p className="pl-1.5 py-0.5">or drag and drop</p>
                  </div>
                  <p className="text-[10px] text-[#656d76] dark:text-[#848d97]">
                    PDF, DOCX, or XLSX up to 100 MiB (MIME sniffed on ingestion)
                  </p>
                </div>
              </div>
            </div>

            {file && (
              <div className="p-2.5 bg-[#ddf4ff]/60 dark:bg-[#388bfd]/15 border border-[#54aeff]/40 rounded-md flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 text-[#0969da] dark:text-[#58a6ff] font-medium truncate">
                  <FileText className="w-4 h-4 shrink-0" />
                  <span className="truncate">{file.name}</span>
                </div>
                <span className="text-[#0969da] dark:text-[#58a6ff] font-mono text-[11px] shrink-0 ml-2">
                  {formatBytes(file.size)}
                </span>
              </div>
            )}

            {uploadStage !== 'idle' && (
              <div className="space-y-1.5 pt-2">
                <div className="flex justify-between text-xs text-[#656d76] dark:text-[#848d97]">
                  <span className="font-medium">
                    {uploadStage === 'intent' && 'Requesting upload intent...'}
                    {uploadStage === 'uploading' && `Uploading directly to quarantine (${uploadProgress}%)...`}
                    {uploadStage === 'completing' && 'Finalizing upload & queueing pipeline...'}
                    {uploadStage === 'done' && 'Upload complete! Ingesting...'}
                  </span>
                  <span className="font-mono">{uploadProgress}%</span>
                </div>
                <div
                  role="progressbar"
                  aria-label="Upload progress"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={uploadStage === 'done' ? 100 : uploadProgress}
                  className="w-full bg-[#eaeef2] dark:bg-[#21262d] rounded-full h-1.5 overflow-hidden"
                >
                  <div
                    className={`h-1.5 rounded-full transition-all duration-200 ${
                      uploadStage === 'done' ? 'bg-[#1a7f37] dark:bg-[#3fb950]' : 'bg-[#0969da] dark:bg-[#2f81f7]'
                    }`}
                    style={{
                      width: `${uploadStage === 'done' ? 100 : uploadProgress}%`,
                    }}
                  />
                </div>
              </div>
            )}

            <ProblemAlert error={error} />

            <div className="pt-2 flex gap-2">
              {uploadStage === 'uploading' && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => abortController.current?.abort()}
                  className="w-full h-8 border-[#cf222e] text-[#cf222e] hover:bg-[#ffebe9] dark:border-[#f85149] dark:text-[#ff7b72] dark:hover:bg-[#490202]"
                >
                  Cancel Upload
                </Button>
              )}
              <Button
                type="submit"
                variant="default"
                disabled={!file || uploadStage !== 'idle'}
                className="w-full h-8"
              >
                {uploadStage === 'idle' && 'Start Upload'}
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
