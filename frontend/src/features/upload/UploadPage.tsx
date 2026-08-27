import React, { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { UploadIntentResponse } from '../../api/types';
import { useAuth } from '../../api/auth';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { UploadCloud, CheckCircle2, FileText } from 'lucide-react';
import { formatBytes } from '../../lib/utils';

interface UploadPageProps {
  onUploadComplete?: () => void;
}

export const UploadPage: React.FC<UploadPageProps> = ({ onUploadComplete }) => {
  const queryClient = useQueryClient();
  const { currentPersona } = useAuth();

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [departmentId, setDepartmentId] = useState(currentPersona?.departmentId || '');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStage, setUploadStage] = useState<'idle' | 'intent' | 'uploading' | 'completing' | 'done'>('idle');
  const [error, setError] = useState<any>(null);

  // Sync default department when persona switches
  React.useEffect(() => {
    if (currentPersona?.departmentId) {
      setDepartmentId(currentPersona.departmentId);
    }
  }, [currentPersona]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0];
      setFile(selected);
      if (!title) {
        // Strip extension as default title
        setTitle(selected.name.replace(/\.[^/.]+$/, ''));
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

      // Step 1: Request Upload Intent (Invariant #1)
      const intent = await api.post<UploadIntentResponse>('/v1/uploads', {
        title: title || file.name,
        department_id: departmentId || currentPersona?.departmentId,
        mime_type: file.type || 'application/pdf',
        byte_size: file.size,
      });

      // Step 2: Direct browser PUT to presigned quarantine URL (Invariant #1)
      setUploadStage('uploading');
      await api.putDirect(
        intent.presigned_url,
        file,
        file.type || 'application/octet-stream',
        (percent) => setUploadProgress(percent)
      );

      // Step 3: Complete upload and enqueue processing chain
      setUploadStage('completing');
      await api.post(`/v1/uploads/${intent.upload_id}/complete`, {
        actual_byte_size: file.size,
      });

      setUploadStage('done');
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['review'] });

      setTimeout(() => {
        if (onUploadComplete) onUploadComplete();
      }, 1200);
    } catch (err: any) {
      setUploadStage('idle');
      setError(err);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-900">Upload Document</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Documents are quarantined, scanned for malware with ClamAV, and classified asynchronously.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ingestion Intent & Quarantine PUT</CardTitle>
          <CardDescription>
            Direct presigned upload (Invariant #1): API never touches raw bytes on the write path.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleUpload} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Document Title
              </label>
              <Input
                type="text"
                placeholder="e.g. Master Services Agreement 2026"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Target Department UUID
              </label>
              <Input
                type="text"
                value={departmentId}
                onChange={(e) => setDepartmentId(e.target.value)}
                placeholder="00000000-0000-0000-0000-000000000010"
                required
              />
              <p className="text-[11px] text-slate-400 mt-1">
                Current Persona Department: {currentPersona?.departmentLabel}
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Document File (.pdf, .docx, .xlsx)
              </label>
              <div className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-slate-300 border-dashed rounded-lg hover:border-blue-400 transition-colors bg-slate-50/50">
                <div className="space-y-2 text-center">
                  <UploadCloud className="mx-auto h-8 w-8 text-slate-400" />
                  <div className="flex text-xs text-slate-600 justify-center">
                    <label className="relative cursor-pointer bg-white rounded-md font-semibold text-blue-600 hover:text-blue-500 focus-within:outline-none px-2 py-0.5 border border-slate-200">
                      <span>Choose file</span>
                      <input
                        type="file"
                        className="sr-only"
                        accept=".pdf,.docx,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        onChange={handleFileChange}
                      />
                    </label>
                    <p className="pl-1.5 py-0.5">or drag and drop</p>
                  </div>
                  <p className="text-[10px] text-slate-400">
                    PDF, DOCX, or XLSX up to 100 MiB (MIME sniffed on ingestion)
                  </p>
                </div>
              </div>
            </div>

            {file && (
              <div className="p-3 bg-blue-50/70 border border-blue-200 rounded-lg flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 text-blue-950 font-medium truncate">
                  <FileText className="w-4 h-4 text-blue-600 shrink-0" />
                  <span className="truncate">{file.name}</span>
                </div>
                <span className="text-blue-700 font-mono shrink-0 ml-2">
                  {formatBytes(file.size)}
                </span>
              </div>
            )}

            {uploadStage !== 'idle' && (
              <div className="space-y-2 pt-2">
                <div className="flex justify-between text-xs text-slate-600">
                  <span className="font-medium">
                    {uploadStage === 'intent' && 'Requesting upload intent...'}
                    {uploadStage === 'uploading' && `Uploading directly to quarantine storage (${uploadProgress}%)...`}
                    {uploadStage === 'completing' && 'Finalizing upload & queueing pipeline...'}
                    {uploadStage === 'done' && 'Upload complete! Ingesting...'}
                  </span>
                  <span className="font-mono">{uploadProgress}%</span>
                </div>
                <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                  <div
                    className={`h-2 rounded-full transition-all duration-200 ${
                      uploadStage === 'done' ? 'bg-emerald-500' : 'bg-blue-600'
                    }`}
                    style={{
                      width: `${uploadStage === 'done' ? 100 : uploadProgress}%`,
                    }}
                  />
                </div>
              </div>
            )}

            <ProblemAlert error={error} />

            <div className="pt-2">
              <Button
                type="submit"
                disabled={!file || uploadStage !== 'idle'}
                className="w-full"
              >
                {uploadStage === 'idle' && 'Start Upload'}
                {uploadStage === 'intent' && 'Preparing Intent...'}
                {uploadStage === 'uploading' && 'Uploading Bytes...'}
                {uploadStage === 'completing' && 'Finalizing...'}
                {uploadStage === 'done' && (
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="w-4 h-4 text-white" /> Success! Redirecting...
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
