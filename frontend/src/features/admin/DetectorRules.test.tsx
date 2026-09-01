import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DetectorRules } from './DetectorRules';
import { api, ApiError } from '../../api/client';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

const wrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

describe('DetectorRules — invariant #10 in the form', () => {
  it('disables save until a validator is chosen', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([]);
    render(<DetectorRules />, { wrapper });

    const user = userEvent.setup();
    const patternInput = screen.getByLabelText(/pattern/i);
    const contextInput = screen.getByLabelText(/context words/i);
    const saveButton = screen.getByRole('button', { name: /save rule/i });

    fireEvent.change(patternInput, { target: { value: '\\bAKIA[0-9A-Z]{16}\\b' } });
    await user.type(contextInput, 'aws, secret');
    expect(saveButton).toBeDisabled();

    const validatorSelect = screen.getByLabelText(/validator kind/i);
    await user.selectOptions(validatorSelect, 'prefix_charset');
    expect(saveButton).toBeEnabled();
  });

  it('disables save with no context words', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([]);
    render(<DetectorRules />, { wrapper });

    const patternInput = screen.getByLabelText(/pattern/i);
    const validatorSelect = screen.getByLabelText(/validator kind/i);
    const saveButton = screen.getByRole('button', { name: /save rule/i });

    fireEvent.change(patternInput, { target: { value: '\\bAKIA[0-9A-Z]{16}\\b' } });
    fireEvent.change(validatorSelect, { target: { value: 'prefix_charset' } });
    expect(saveButton).toBeDisabled();
  });

  it('shows preview matches as offsets, never the matched text', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([]);
    vi.spyOn(api, 'post').mockResolvedValue({
      matches: [{ char_start: 11, char_end: 31, score: 0.9 }],
    });

    render(<DetectorRules />, { wrapper });

    const user = userEvent.setup();
    const patternInput = screen.getByLabelText(/pattern/i);
    const contextInput = screen.getByLabelText(/context words/i);
    const validatorSelect = screen.getByLabelText(/validator kind/i);
    const sampleInput = screen.getByLabelText(/sample text/i);
    const previewButton = screen.getByRole('button', { name: /run preview/i });

    fireEvent.change(patternInput, { target: { value: '\\bAKIA[0-9A-Z]{16}\\b' } });
    await user.type(contextInput, 'aws, secret');
    await user.selectOptions(validatorSelect, 'prefix_charset');
    await user.type(sampleInput, 'aws secret AKIAJJJJJJJJJJJJJJJJ');
    await user.click(previewButton);

    const matchesContainer = await screen.findByTestId('preview-matches');
    expect(within(matchesContainer).getByText(/11–31/)).toBeInTheDocument();
    expect(within(matchesContainer).queryByText(/AKIAJ/)).not.toBeInTheDocument();
  });

  it('surfaces a server pattern rejection', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([]);
    vi.spyOn(api, 'post').mockRejectedValue(
      new ApiError(422, 'pattern is not safe to run', {
        type: 'about:blank',
        title: 'Unprocessable Entity',
        status: 422,
        detail: 'pattern is not safe to run',
      })
    );

    render(<DetectorRules />, { wrapper });

    const user = userEvent.setup();
    const entityInput = screen.getByLabelText(/entity type/i);
    const patternInput = screen.getByLabelText(/pattern/i);
    const contextInput = screen.getByLabelText(/context words/i);
    const validatorSelect = screen.getByLabelText(/validator kind/i);
    const saveButton = screen.getByRole('button', { name: /save rule/i });

    await user.type(entityInput, 'company_key');
    fireEvent.change(patternInput, { target: { value: '(a+)+$' } });
    await user.type(contextInput, 'aws, secret');
    await user.selectOptions(validatorSelect, 'prefix_charset');
    await user.click(saveButton);

    expect(await screen.findByText(/not safe to run/i)).toBeInTheDocument();
  });
});
