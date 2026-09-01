import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  DetectorRuleOut,
  DetectorRuleCreate,
  DetectorPreviewResponse,
} from '../../api/types';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { ProblemAlert } from '../../components/common/ProblemAlert';
import { TableSkeleton } from '../../components/common/LoadingSkeleton';
import { ShieldAlert, Plus, Trash2, Eye, CheckCircle2 } from 'lucide-react';

const VALIDATOR_OPTIONS = [
  { value: '', label: '-- Select a Structural Validator --' },
  { value: 'prefix_charset', label: 'Prefix & Character Set (API Keys, Tokens)' },
  { value: 'luhn', label: 'Luhn Algorithm (Credit / Payment Cards)' },
  { value: 'mod97', label: 'ISO 7064 Mod 97-10 (IBAN / Bank Accounts)' },
  { value: 'entropy', label: 'Shannon Entropy (High-Entropy Secrets)' },
  { value: 'checksum_suffix', label: 'Checksum Suffix (Hash-Validated Keys)' },
];

export const DetectorRules: React.FC = () => {
  const queryClient = useQueryClient();

  const [entityType, setEntityType] = useState('company_api_key');
  const [pattern, setPattern] = useState('');
  const [contextWords, setContextWords] = useState('');
  const [validatorKind, setValidatorKind] = useState('');
  const [levelRank, setLevelRank] = useState(4);
  const [prefix, setPrefix] = useState('AKIA');
  const [length, setLength] = useState('20');
  const [charset, setCharset] = useState('A-Z0-9');
  const [minBits, setMinBits] = useState('3.0');
  const [sampleText, setSampleText] = useState('');
  const [previewResult, setPreviewResult] = useState<DetectorPreviewResponse | null>(null);
  const [formError, setFormError] = useState<unknown>(null);

  const {
    data: rules,
    isLoading: rulesLoading,
    error: rulesError,
  } = useQuery({
    queryKey: ['detector-rules'],
    queryFn: () => api.get<DetectorRuleOut[]>('/v1/admin/detectors'),
  });

  const createRuleMutation = useMutation({
    mutationFn: (payload: DetectorRuleCreate) => api.post<DetectorRuleOut>('/v1/admin/detectors', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['detector-rules'] });
      setPattern('');
      setContextWords('');
      setValidatorKind('');
      setFormError(null);
    },
    onError: (err) => setFormError(err),
  });

  const deleteRuleMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/v1/admin/detectors/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['detector-rules'] });
      setFormError(null);
    },
    onError: (err) => setFormError(err),
  });

  const previewMutation = useMutation({
    mutationFn: (payload: any) =>
      api.post<DetectorPreviewResponse>('/v1/admin/detectors/preview', payload),
    onSuccess: (data) => {
      setPreviewResult(data);
      setFormError(null);
    },
    onError: (err) => {
      setPreviewResult(null);
      setFormError(err);
    },
  });

  const buildValidatorConfig = () => {
    if (validatorKind === 'prefix_charset') {
      const config: Record<string, any> = {};
      if (prefix) config.prefix = prefix;
      if (length) config.length = parseInt(length, 10);
      if (charset) config.charset = charset;
      return config;
    }
    if (validatorKind === 'entropy') {
      return { min_bits_per_char: parseFloat(minBits) || 3.0 };
    }
    return {};
  };

  const parsedContextWords = contextWords
    .split(',')
    .map((w) => w.trim())
    .filter(Boolean);

  const canSave =
    entityType.trim().length > 0 &&
    pattern.trim().length > 0 &&
    parsedContextWords.length > 0 &&
    validatorKind.trim().length > 0;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    createRuleMutation.mutate({
      entity_type: entityType.trim(),
      pattern: pattern.trim(),
      context_words: parsedContextWords,
      validator_kind: validatorKind,
      validator_config: buildValidatorConfig(),
      level_rank: levelRank,
      enabled: true,
    });
  };

  const handlePreview = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pattern.trim() || !parsedContextWords.length || !validatorKind || !sampleText.trim()) return;
    previewMutation.mutate({
      entity_type: entityType.trim() || 'custom_entity',
      pattern: pattern.trim(),
      context_words: parsedContextWords,
      validator_kind: validatorKind,
      validator_config: buildValidatorConfig(),
      level_rank: levelRank,
      sample_text: sampleText,
    });
  };

  return (
    <div className="space-y-6">
      <ProblemAlert error={formError || rulesError} />

      {/* 1. Rule Builder Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="w-4 h-4 text-[#cf222e] dark:text-[#f85149]" />
            Custom Detector Rule Builder
          </CardTitle>
          <CardDescription>
            Invariant #10 compliant: A detector requires a regex pattern, context words scored in a ±50 char window, AND a structural validator.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="entity-type-input" className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                  Entity Type (Identifier)
                </label>
                <Input
                  id="entity-type-input"
                  aria-label="Entity Type"
                  value={entityType}
                  onChange={(e) => setEntityType(e.target.value)}
                  placeholder="e.g. company_api_key"
                  required
                />
              </div>

              <div>
                <label htmlFor="level-rank-select" className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                  Contributed Security Level
                </label>
                <select
                  id="level-rank-select"
                  aria-label="Level Rank"
                  value={levelRank}
                  onChange={(e) => setLevelRank(Number(e.target.value))}
                  className="w-full h-9 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] px-3 py-1 text-xs text-[#1f2328] dark:text-[#e6edf3]"
                >
                  <option value={4}>Restricted (Rank 4)</option>
                  <option value={3}>Confidential (Rank 3)</option>
                  <option value={2}>Internal (Rank 2)</option>
                  <option value={1}>Public (Rank 1)</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="pattern-input" className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                  Pattern (Regex)
                </label>
                <Input
                  id="pattern-input"
                  aria-label="Pattern"
                  value={pattern}
                  onChange={(e) => setPattern(e.target.value)}
                  placeholder="e.g. \bAKIA[0-9A-Z]{16}\b"
                  required
                />
              </div>

              <div>
                <label htmlFor="context-words-input" className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                  Context Words (Comma-separated)
                </label>
                <Input
                  id="context-words-input"
                  aria-label="Context Words"
                  value={contextWords}
                  onChange={(e) => setContextWords(e.target.value)}
                  placeholder="e.g. aws, secret, credential"
                  required
                />
              </div>
            </div>

            <div>
              <label htmlFor="validator-kind-select" className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
                Validator Kind (Required by Invariant #10)
              </label>
              <select
                id="validator-kind-select"
                aria-label="Validator Kind"
                value={validatorKind}
                onChange={(e) => setValidatorKind(e.target.value)}
                className="w-full h-9 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] px-3 py-1 text-xs text-[#1f2328] dark:text-[#e6edf3]"
                required
              >
                {VALIDATOR_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {validatorKind === 'prefix_charset' && (
              <div className="p-3 bg-[#f6f8fa] dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d] grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold mb-1">Prefix</label>
                  <Input value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder="AKIA" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold mb-1">Length</label>
                  <Input value={length} onChange={(e) => setLength(e.target.value)} placeholder="20" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold mb-1">Charset</label>
                  <Input value={charset} onChange={(e) => setCharset(e.target.value)} placeholder="A-Z0-9" />
                </div>
              </div>
            )}

            {validatorKind === 'entropy' && (
              <div className="p-3 bg-[#f6f8fa] dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d]">
                <label className="block text-[11px] font-semibold mb-1">Min Bits Per Character</label>
                <Input value={minBits} onChange={(e) => setMinBits(e.target.value)} placeholder="3.0" />
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="submit"
                disabled={!canSave || createRuleMutation.isPending}
                className="gap-1.5"
              >
                <Plus className="w-3.5 h-3.5" />
                Save Rule
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* 2. Rule Preview Sandbox */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Eye className="w-4 h-4 text-[#0969da] dark:text-[#2f81f7]" />
            Test & Preview Pattern (Invariant #12 Sandbox)
          </CardTitle>
          <CardDescription>
            Test your detector against sample document text. Invariant #12 holds: responses contain character offsets only, never matched sensitive values.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label htmlFor="sample-text-input" className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1">
              Sample Text
            </label>
            <textarea
              id="sample-text-input"
              aria-label="Sample Text"
              value={sampleText}
              onChange={(e) => setSampleText(e.target.value)}
              rows={3}
              placeholder="Paste sample text to test pattern matching and context scoring..."
              className="w-full rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] p-2 text-xs font-mono text-[#1f2328] dark:text-[#e6edf3]"
            />
          </div>

          <div className="flex justify-between items-center">
            <Button
              type="button"
              variant="outline"
              onClick={handlePreview}
              disabled={!pattern || !validatorKind || !sampleText.trim() || previewMutation.isPending}
              className="gap-1.5"
            >
              <Eye className="w-3.5 h-3.5" />
              Run Preview
            </Button>

            {previewResult && (
              <span className="text-xs text-[#656d76] dark:text-[#848d97]">
                {previewResult.matches.length} match(es) detected
              </span>
            )}
          </div>

          {previewResult && previewResult.matches.length > 0 && (
            <div
              data-testid="preview-matches"
              className="p-3 bg-[#f6f8fa] dark:bg-[#161b22] rounded-md border border-[#d0d7de] dark:border-[#30363d] space-y-2"
            >
              <div className="text-xs font-bold text-[#1f2328] dark:text-[#e6edf3]">
                Matched Spans (Offsets Only):
              </div>
              <div className="flex flex-wrap gap-2">
                {previewResult.matches.map((m, idx) => (
                  <div
                    key={idx}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-white dark:bg-[#0d1117] border border-[#d0d7de] dark:border-[#30363d] text-xs font-mono"
                  >
                    <CheckCircle2 className="w-3 h-3 text-[#1a7f37] dark:text-[#3fb950]" />
                    <span>
                      Span: {m.char_start}–{m.char_end}
                    </span>
                    <span className="text-[10px] text-[#656d76] dark:text-[#848d97]">
                      (Score: {m.score.toFixed(2)})
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 3. Existing Custom Rules */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Configured Tenant Rules</CardTitle>
          <CardDescription>
            Custom regex detector rules registered for this tenant.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {rulesLoading ? (
            <TableSkeleton rows={3} cols={5} />
          ) : rules && rules.length > 0 ? (
            <div className="bg-white dark:bg-[#0d1117] rounded-md border border-[#d0d7de] dark:border-[#30363d] overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Entity Type</TableHead>
                    <TableHead>Pattern</TableHead>
                    <TableHead>Validator</TableHead>
                    <TableHead>Level Rank</TableHead>
                    <TableHead className="w-16">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rules.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="font-mono text-xs font-bold">{r.entity_type}</TableCell>
                      <TableCell className="font-mono text-[11px] max-w-xs truncate">{r.pattern}</TableCell>
                      <TableCell className="text-xs">{r.validator_kind}</TableCell>
                      <TableCell className="text-xs font-mono">Rank {r.level_rank}</TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => deleteRuleMutation.mutate(r.id)}
                          disabled={deleteRuleMutation.isPending}
                          className="h-7 w-7 p-0 text-[#cf222e] hover:bg-[#ffebe9] dark:hover:bg-[#490202]"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-xs text-[#656d76] dark:text-[#848d97]">
              No custom detector rules registered for this tenant.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
