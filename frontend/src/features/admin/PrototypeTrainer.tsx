import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  DocTypeOut,
  DocumentPage,
  DocumentListItem,
  TrainPrototypeResponse,
} from '../../api/types';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { Cpu, CheckCircle2, Sparkles } from 'lucide-react';

export const PrototypeTrainer: React.FC = () => {
  const queryClient = useQueryClient();

  const [selectedDocTypeId, setSelectedDocTypeId] = useState<string>('');
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [trainResult, setTrainResult] = useState<TrainPrototypeResponse | null>(null);
  const [trainError, setTrainError] = useState<unknown>(null);

  const { data: docTypes, isLoading: docTypesLoading } = useQuery({
    queryKey: ['doc-types'],
    queryFn: () => api.get<DocTypeOut[]>('/v1/admin/doc-types'),
  });

  // Fetch documents to select ready samples (picker excludes non-ready per spec)
  const { data: docsPage, isLoading: docsLoading } = useQuery({
    queryKey: ['documents-for-training'],
    queryFn: () => api.get<DocumentPage>('/v1/documents?limit=100'),
  });

  const readyDocs = (docsPage?.items || []).filter((d) => d.status === 'ready');

  const trainMutation = useMutation({
    mutationFn: () =>
      api.post<TrainPrototypeResponse>(`/v1/admin/doc-types/${selectedDocTypeId}/prototype`, {
        document_ids: selectedDocIds,
      }),
    onSuccess: (data) => {
      setTrainResult(data);
      setTrainError(null);
      queryClient.invalidateQueries({ queryKey: ['doc-types'] });
    },
    onError: (err) => {
      setTrainResult(null);
      setTrainError(err);
    },
  });

  const handleToggleDoc = (docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : prev.length < 10 ? [...prev, docId] : prev
    );
  };

  const sampleCount = selectedDocIds.length;
  const isCountValid = sampleCount >= 5 && sampleCount <= 10;
  const canTrain = selectedDocTypeId !== '' && isCountValid && !trainMutation.isPending;

  return (
    <div className="space-y-6">
      <ProblemAlert error={trainError} />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Cpu className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
            Few-Shot Document Type Classifier (Prototypes)
          </CardTitle>
          <CardDescription>
            Train a prototype embedding vector from 5–10 representative sample documents. Stored embeddings are computed once (#6) and matched before ML classification.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* 1. Target Doc Type Picker */}
          <div>
            <label htmlFor="target-doc-type-select" className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
              Target Document Type
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
                {docTypes?.map((dt) => (
                  <option key={dt.id} value={dt.id}>
                    {dt.name} {dt.description ? `(${dt.description})` : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* 2. Sample Documents Multi-Select */}
          <div>
            <div className="flex justify-between items-center mb-2">
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
                {sampleCount} / 5–10 selected
              </span>
            </div>

            {docsLoading ? (
              <TableSkeleton rows={4} cols={3} />
            ) : readyDocs.length === 0 ? (
              <p className="text-xs text-[#656d76] dark:text-[#848d97] p-4 bg-[#f6f8fa] dark:bg-[#161b22] rounded border border-[#d0d7de] dark:border-[#30363d]">
                No processed documents with status `ready` available. Upload and process documents before training.
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

          {/* 3. Train Action */}
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              onClick={() => trainMutation.mutate()}
              disabled={!canTrain}
              className="gap-1.5"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Train Prototype Vector
            </Button>
          </div>

          {/* 4. Success Result Display */}
          {trainResult && (
            <div className="p-4 bg-[#dafbe1] dark:bg-[#033a16] text-[#1a7f37] dark:text-[#3fb950] rounded-md border border-[#4ac26b] flex items-start gap-3">
              <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5" />
              <div className="text-xs space-y-1">
                <div className="font-bold">Prototype Trained Successfully!</div>
                <div>
                  Averaged centroid vector generated from {trainResult.sample_count} sample documents with {trainResult.dimension} embedding dimensions.
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
