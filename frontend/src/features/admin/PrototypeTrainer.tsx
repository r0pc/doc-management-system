import React, { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  DocTypeOut,
  DocTypePrototypeOut,
  DocumentPage,
  DocumentListItem,
  TrainPrototypeResponse,
} from '../../api/types';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { formatBytes, formatDate } from '../../lib/utils';
import {
  Cpu,
  CheckCircle2,
  Sparkles,
  UploadCloud,
  FileText,
  X,
  ShieldCheck,
  FolderOpen,
  RotateCcw,
  Trash2,
} from 'lucide-react';

type InputMode = 'upload' | 'repository';

export const PrototypeTrainer: React.FC = () => {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [inputMode, setInputMode] = useState<InputMode>('upload');
  const [selectedDocTypeId, setSelectedDocTypeId] = useState<string>('');
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [trainResult, setTrainResult] = useState<TrainPrototypeResponse | null>(null);
  const [successNotice, setSuccessNotice] = useState<string | null>(null);
  const [trainError, setTrainError] = useState<unknown>(null);

  const { data: docTypes, isLoading: docTypesLoading } = useQuery({
    queryKey: ['doc-types'],
    queryFn: () => api.get<DocTypeOut[]>('/v1/admin/doc-types'),
  });

  const { data: prototypes, isLoading: prototypesLoading } = useQuery({
    queryKey: ['prototypes'],
    queryFn: () => api.get<DocTypePrototypeOut[]>('/v1/admin/prototypes'),
  });

  // Fetch documents for repository selection mode
  const { data: docsPage, isLoading: docsLoading } = useQuery({
    queryKey: ['documents-for-training'],
    queryFn: () => api.get<DocumentPage>('/v1/documents?limit=100'),
    enabled: inputMode === 'repository',
  });

  const readyDocs = (docsPage?.items || []).filter((d) => d.status === 'ready');

  // Mutation for repository documents
  const trainFromRepoMutation = useMutation({
    mutationFn: () =>
      api.post<TrainPrototypeResponse>(`/v1/admin/doc-types/${selectedDocTypeId}/prototype`, {
        document_ids: selectedDocIds,
      }),
    onSuccess: (data) => {
      setTrainResult(data);
      setSuccessNotice(null);
      setTrainError(null);
      queryClient.invalidateQueries({ queryKey: ['prototypes'] });
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
    },
    onError: (err) => {
      setTrainResult(null);
      setTrainError(err);
    },
  });

  // Mutation for direct file upload
  const trainFromUploadMutation = useMutation({
    mutationFn: () => {
      const formData = new FormData();
      uploadedFiles.forEach((file) => {
        formData.append('files', file);
      });
      return api.post<TrainPrototypeResponse>(
        `/v1/admin/doc-types/${selectedDocTypeId}/prototype-upload`,
        formData
      );
    },
    onSuccess: (data) => {
      setTrainResult(data);
      setSuccessNotice(null);
      setTrainError(null);
      setUploadedFiles([]);
      queryClient.invalidateQueries({ queryKey: ['prototypes'] });
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
    },
    onError: (err) => {
      setTrainResult(null);
      setTrainError(err);
    },
  });

  // Mutation to reset single prototype
  const resetSingleMutation = useMutation({
    mutationFn: (docTypeId: string) =>
      api.delete(`/v1/admin/doc-types/${docTypeId}/prototype`),
    onSuccess: (_, docTypeId) => {
      const dtName = docTypes?.find((d) => d.id === docTypeId)?.name || 'Document type';
      setTrainResult(null);
      setSuccessNotice(`Prototype vector for "${dtName}" was successfully reset.`);
      setTrainError(null);
      queryClient.invalidateQueries({ queryKey: ['prototypes'] });
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
    },
    onError: (err) => {
      setTrainError(err);
    },
  });

  // Mutation to reset all prototypes
  const resetAllMutation = useMutation({
    mutationFn: () => api.delete('/v1/admin/prototypes'),
    onSuccess: () => {
      setTrainResult(null);
      setSuccessNotice('All prototype vectors were successfully reset.');
      setTrainError(null);
      queryClient.invalidateQueries({ queryKey: ['prototypes'] });
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
    },
    onError: (err) => {
      setTrainError(err);
    },
  });

  const handleFilesAdded = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files);
      setUploadedFiles((prev) => {
        const existingNames = new Set(prev.map((f) => f.name));
        const uniqueNew = newFiles.filter((f) => !existingNames.has(f.name));
        const combined = [...prev, ...uniqueNew];
        return combined.slice(0, 10);
      });
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleRemoveFile = (index: number) => {
    setUploadedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleToggleDoc = (docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : prev.length < 10
        ? [...prev, docId]
        : prev
    );
  };

  const isUploading = trainFromUploadMutation.isPending || trainFromRepoMutation.isPending;

  const currentCount = inputMode === 'upload' ? uploadedFiles.length : selectedDocIds.length;
  const isCountValid = currentCount >= 5 && currentCount <= 10;
  const canTrain = selectedDocTypeId !== '' && isCountValid && !isUploading;

  const handleTrain = () => {
    if (!canTrain) return;
    if (inputMode === 'upload') {
      trainFromUploadMutation.mutate();
    } else {
      trainFromRepoMutation.mutate();
    }
  };

  const selectedDocType = docTypes?.find((d) => d.id === selectedDocTypeId);
  const selectedDocTypePrototype = prototypes?.find((p) => p.doc_type_id === selectedDocTypeId);

  const docTypeMap = new Map((docTypes || []).map((dt) => [dt.id, dt.name]));

  return (
    <div className="space-y-6" data-testid="prototype-trainer">
      <ProblemAlert error={trainError} />

      {successNotice && (
        <div className="p-3 bg-[#dafbe1] dark:bg-[#033a16] text-[#1a7f37] dark:text-[#3fb950] rounded-md border border-[#4ac26b] flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 font-medium">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{successNotice}</span>
          </div>
          <button
            type="button"
            onClick={() => setSuccessNotice(null)}
            className="text-[#1a7f37] dark:text-[#3fb950] hover:opacity-75"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Main Training Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Cpu className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
            Few-Shot Document Type Classifier (Prototypes)
          </CardTitle>
          <CardDescription>
            Train a prototype embedding vector from 5–10 representative sample documents. Stored embeddings are matched by cosine similarity before ML cascade fallback.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* 1. Target Doc Type Picker */}
          <div className="space-y-2">
            <div>
              <label
                htmlFor="target-doc-type-select"
                className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1"
              >
                Target Document Type *
              </label>
              {docTypesLoading ? (
                <div className="h-9 bg-gray-100 dark:bg-gray-800 animate-pulse rounded" />
              ) : (
                <select
                  id="target-doc-type-select"
                  aria-label="Target Document Type"
                  value={selectedDocTypeId}
                  onChange={(e) => setSelectedDocTypeId(e.target.value)}
                  className="w-full h-9 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] px-3 py-1 text-xs text-[#1f2328] dark:text-[#e6edf3]"
                >
                  <option value="">-- Select Document Type to Train --</option>
                  {docTypes?.map((dt) => {
                    const hasProto = prototypes?.some((p) => p.doc_type_id === dt.id);
                    return (
                      <option key={dt.id} value={dt.id}>
                        {dt.name} {hasProto ? '★ [Active Prototype]' : ''} {dt.description ? `(${dt.description})` : ''}
                      </option>
                    );
                  })}
                </select>
              )}
            </div>

            {/* Active prototype info + Reset button for the selected document type */}
            {selectedDocTypePrototype && (
              <div className="flex items-center justify-between p-2.5 bg-[#ddf4ff]/50 dark:bg-[#1f6feb]/10 border border-[#54aeff]/30 rounded-md text-xs">
                <div className="flex items-center gap-2 text-[#0969da] dark:text-[#2f81f7]">
                  <CheckCircle2 className="w-4 h-4 shrink-0 text-[#1a7f37] dark:text-[#3fb950]" />
                  <span>
                    <strong>Active Prototype Trained:</strong> Centroid derived from{' '}
                    {selectedDocTypePrototype.sample_count} samples (updated{' '}
                    {formatDate(selectedDocTypePrototype.updated_at)})
                  </span>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (
                      window.confirm(
                        `Are you sure you want to reset the prototype vector for "${selectedDocType?.name}"? Incoming documents will no longer match this prototype.`
                      )
                    ) {
                      resetSingleMutation.mutate(selectedDocTypeId);
                    }
                  }}
                  disabled={resetSingleMutation.isPending}
                  className="h-7 text-xs text-[#cf222e] dark:text-[#f85149] hover:bg-[#ffebe9] dark:hover:bg-[#490202] border-[#cf222e]/30 gap-1"
                >
                  <RotateCcw className={`w-3 h-3 ${resetSingleMutation.isPending ? 'animate-spin' : ''}`} />
                  {resetSingleMutation.isPending ? 'Resetting...' : 'Reset Prototype Effect'}
                </Button>
              </div>
            )}
          </div>

          {/* 2. Mode Selector: Direct Upload vs Repository Selection */}
          <div className="space-y-3">
            <div className="flex border-b border-[#d0d7de] dark:border-[#30363d] space-x-4">
              <button
                type="button"
                onClick={() => setInputMode('upload')}
                className={`flex items-center gap-1.5 pb-2 text-xs font-semibold border-b-2 transition-colors ${
                  inputMode === 'upload'
                    ? 'border-[#0969da] text-[#0969da] dark:border-[#2f81f7] dark:text-[#2f81f7]'
                    : 'border-transparent text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3]'
                }`}
              >
                <UploadCloud className="w-3.5 h-3.5" />
                Upload Sample Files Directly
              </button>
              <button
                type="button"
                onClick={() => setInputMode('repository')}
                className={`flex items-center gap-1.5 pb-2 text-xs font-semibold border-b-2 transition-colors ${
                  inputMode === 'repository'
                    ? 'border-[#0969da] text-[#0969da] dark:border-[#2f81f7] dark:text-[#2f81f7]'
                    : 'border-transparent text-[#656d76] dark:text-[#848d97] hover:text-[#1f2328] dark:hover:text-[#e6edf3]'
                }`}
              >
                <FolderOpen className="w-3.5 h-3.5" />
                Select from Ingested Repository
              </button>
            </div>

            {/* A. DIRECT UPLOAD MODE */}
            {inputMode === 'upload' && (
              <div className="space-y-3">
                <div className="p-3 bg-[#ddf4ff]/50 dark:bg-[#1f6feb]/10 border border-[#54aeff]/30 rounded-md text-[11px] text-[#0969da] dark:text-[#2f81f7] flex items-start gap-2">
                  <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold">In-Memory Training Guarantee:</span> Uploaded
                    sample files are scanned for malware, text-extracted, and converted to embedding
                    vectors purely in memory. They are <strong>never saved</strong> to object
                    storage or stored in repository document tables.
                  </div>
                </div>

                <div className="flex justify-between items-center">
                  <span className="text-xs font-medium text-[#1f2328] dark:text-[#e6edf3]">
                    Upload 5–10 Sample Files (PDF, DOCX, XLSX, TXT)
                  </span>
                  <span
                    className={`text-xs font-mono font-medium ${
                      isCountValid
                        ? 'text-[#1a7f37] dark:text-[#3fb950]'
                        : 'text-[#cf222e] dark:text-[#f85149]'
                    }`}
                  >
                    {uploadedFiles.length} / 5–10 files
                  </span>
                </div>

                {/* Dropzone / Upload button area */}
                <div
                  onClick={() => fileInputRef.current?.click()}
                  className="border-2 border-dashed border-[#d0d7de] dark:border-[#30363d] hover:border-[#0969da] dark:hover:border-[#2f81f7] rounded-lg p-5 text-center cursor-pointer transition-colors bg-[#f6f8fa] dark:bg-[#161b22]"
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.docx,.xlsx,.txt"
                    onChange={handleFilesAdded}
                    className="hidden"
                    aria-label="Upload sample documents"
                  />
                  <UploadCloud className="w-6 h-6 mx-auto text-[#656d76] dark:text-[#848d97] mb-1.5" />
                  <div className="text-xs font-medium text-[#1f2328] dark:text-[#e6edf3]">
                    Click to select sample files from your computer
                  </div>
                  <div className="text-[10px] text-[#656d76] dark:text-[#848d97] mt-0.5">
                    Supports .pdf, .docx, .xlsx, and .txt files (max 10 files)
                  </div>
                </div>

                {/* Uploaded files list */}
                {uploadedFiles.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="flex justify-between items-center text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3]">
                      <span>Selected Files ({uploadedFiles.length})</span>
                      <button
                        type="button"
                        onClick={() => setUploadedFiles([])}
                        className="text-[11px] text-[#cf222e] dark:text-[#f85149] hover:underline"
                      >
                        Clear all
                      </button>
                    </div>

                    <div className="max-h-48 overflow-y-auto border border-[#d0d7de] dark:border-[#30363d] rounded-md divide-y divide-[#d0d7de] dark:divide-[#30363d] bg-white dark:bg-[#0d1117]">
                      {uploadedFiles.map((file, idx) => (
                        <div
                          key={`${file.name}-${idx}`}
                          className="flex items-center justify-between px-3 py-2 text-xs"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <FileText className="w-3.5 h-3.5 text-[#0969da] dark:text-[#2f81f7] shrink-0" />
                            <span className="font-mono truncate text-[#1f2328] dark:text-[#e6edf3]">
                              {file.name}
                            </span>
                            <span className="text-[10px] text-[#656d76] dark:text-[#848d97]">
                              ({formatBytes(file.size)})
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleRemoveFile(idx)}
                            className="text-[#656d76] hover:text-[#cf222e] dark:hover:text-[#f85149] p-0.5 rounded"
                            aria-label={`Remove ${file.name}`}
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* B. REPOSITORY SELECTION MODE */}
            {inputMode === 'repository' && (
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <label className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3]">
                    Select 5–10 Ready Sample Documents
                  </label>
                  <span
                    className={`text-xs font-mono font-medium ${
                      isCountValid
                        ? 'text-[#1a7f37] dark:text-[#3fb950]'
                        : 'text-[#cf222e] dark:text-[#f85149]'
                    }`}
                  >
                    {selectedDocIds.length} / 5–10 selected
                  </span>
                </div>

                {docsLoading ? (
                  <TableSkeleton rows={4} cols={3} />
                ) : readyDocs.length === 0 ? (
                  <p className="text-xs text-[#656d76] dark:text-[#848d97] p-4 bg-[#f6f8fa] dark:bg-[#161b22] rounded border border-[#d0d7de] dark:border-[#30363d]">
                    No processed documents with status `ready` available. Use direct upload above or
                    process documents before training.
                  </p>
                ) : (
                  <div className="max-h-60 overflow-y-auto border border-[#d0d7de] dark:border-[#30363d] rounded-md divide-y divide-[#d0d7de] dark:divide-[#30363d]">
                    {readyDocs.map((doc: DocumentListItem) => {
                      const isChecked = selectedDocIds.includes(doc.id);
                      return (
                        <label
                          key={doc.id}
                          className={`flex items-center gap-3 px-3 py-2 text-xs hover:bg-[#f6f8fa] dark:hover:bg-[#161b22] cursor-pointer ${
                            isChecked ? 'bg-[#ddf4ff] dark:bg-[#04244a]' : ''
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => handleToggleDoc(doc.id)}
                            disabled={!isChecked && selectedDocIds.length >= 10}
                            className="rounded border-gray-300 text-[#0969da] focus:ring-[#0969da]"
                          />
                          <span className="font-mono text-[#1f2328] dark:text-[#e6edf3] flex-1 truncate">
                            {doc.filename}
                          </span>
                          <span className="text-[10px] text-[#656d76] dark:text-[#848d97]">
                            {doc.doc_type || 'Unclassified'}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 3. Train Action */}
          <div className="flex justify-end gap-2 pt-2 border-t border-[#d0d7de] dark:border-[#30363d]">
            <Button
              type="button"
              onClick={handleTrain}
              disabled={!canTrain}
              className="gap-1.5"
            >
              <Sparkles className={`w-3.5 h-3.5 ${isUploading ? 'animate-spin' : ''}`} />
              {isUploading
                ? 'Processing & Training...'
                : inputMode === 'upload'
                ? 'Train from Uploaded Files'
                : 'Train from Repository Samples'}
            </Button>
          </div>

          {/* 4. Success Result Display */}
          {trainResult && (
            <div className="p-4 bg-[#dafbe1] dark:bg-[#033a16] text-[#1a7f37] dark:text-[#3fb950] rounded-md border border-[#4ac26b] flex items-start gap-3">
              <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" />
              <div className="text-xs space-y-1">
                <div className="font-bold">Prototype Trained Successfully!</div>
                <div>
                  Averaged centroid vector generated from {trainResult.sample_count} sample
                  documents with {trainResult.dimension} embedding dimensions.
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Active Prototypes Table Card */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
              Active Trained Prototypes ({prototypes?.length || 0})
            </CardTitle>
            <CardDescription className="text-xs">
              Configured class prototype centroids that are matched before classifier cascade.
            </CardDescription>
          </div>
          {prototypes && prototypes.length > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                if (
                  window.confirm(
                    'Are you sure you want to reset ALL trained prototype vectors? Incoming documents will fall back to standard cascade classification.'
                  )
                ) {
                  resetAllMutation.mutate();
                }
              }}
              disabled={resetAllMutation.isPending}
              className="text-xs text-[#cf222e] dark:text-[#f85149] hover:bg-[#ffebe9] dark:hover:bg-[#490202] border-[#cf222e]/30 gap-1.5 h-8"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {resetAllMutation.isPending ? 'Resetting All...' : 'Reset All Prototypes'}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {prototypesLoading ? (
            <TableSkeleton rows={2} cols={3} />
          ) : !prototypes || prototypes.length === 0 ? (
            <p className="text-xs text-[#656d76] dark:text-[#848d97] p-4 bg-[#f6f8fa] dark:bg-[#161b22] rounded border border-[#d0d7de] dark:border-[#30363d]">
              No document type prototypes have been trained yet. Select a target document type above and upload 5–10 samples to train one.
            </p>
          ) : (
            <div className="border border-[#d0d7de] dark:border-[#30363d] rounded-md overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-[#f6f8fa] dark:bg-[#161b22] border-b border-[#d0d7de] dark:border-[#30363d] font-semibold text-[#1f2328] dark:text-[#e6edf3]">
                  <tr>
                    <th className="px-3 py-2">Document Type</th>
                    <th className="px-3 py-2">Sample Count</th>
                    <th className="px-3 py-2">Last Updated</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#d0d7de] dark:divide-[#30363d] bg-white dark:bg-[#0d1117]">
                  {prototypes.map((proto) => {
                    const dtName = docTypeMap.get(proto.doc_type_id) || proto.doc_type_id;
                    return (
                      <tr key={proto.id} className="hover:bg-[#f6f8fa] dark:hover:bg-[#161b22]/50">
                        <td className="px-3 py-2.5 font-medium text-[#1f2328] dark:text-[#e6edf3]">
                          {dtName}
                        </td>
                        <td className="px-3 py-2.5 text-[#656d76] dark:text-[#848d97] font-mono">
                          {proto.sample_count} samples
                        </td>
                        <td className="px-3 py-2.5 text-[#656d76] dark:text-[#848d97]">
                          {formatDate(proto.updated_at)}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              if (
                                window.confirm(
                                  `Are you sure you want to reset the prototype vector for "${dtName}"?`
                                )
                              ) {
                                resetSingleMutation.mutate(proto.doc_type_id);
                              }
                            }}
                            disabled={resetSingleMutation.isPending}
                            className="h-7 px-2 text-xs text-[#cf222e] dark:text-[#f85149] hover:bg-[#ffebe9] dark:hover:bg-[#490202] gap-1"
                          >
                            <RotateCcw className="w-3 h-3" />
                            Reset Effect
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
