import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { DepartmentPicker } from './DepartmentPicker';
import { rootDepartmentId, withRoot, Department } from './useDepartments';
import { renderWithProviders, jsonResponse } from '../../test-utils';

/**
 * The picker is the UI half of #25's department axis.
 *
 * The tenant root is locked on because the API refuses a set without it. If the
 * checkbox were merely pre-checked and clearable, a user could uncheck it, hit
 * Save, and get a stored set that differs from what they were shown — the
 * server would silently add the root back.
 */

const ROOT: Department = {
  id: 'dept-hq',
  name: 'HQ',
  parent_id: null,
  is_root: true,
  assignable: true,
};
const HR: Department = {
  id: 'dept-hr',
  name: 'HR',
  parent_id: 'dept-hq',
  is_root: false,
  assignable: true,
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn((url: string) =>
    Promise.resolve(
      String(url).includes('/v1/departments') ? jsonResponse([ROOT, HR]) : jsonResponse({})
    )
  );
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Drives the picker as a real caller would, holding the selection in state. */
const Harness = () => {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  return (
    <>
      <DepartmentPicker selected={selected} onChange={setSelected} />
      <output data-testid="selection">{[...selected].sort().join(',')}</output>
    </>
  );
};

const option = (name: string) =>
  document.querySelector(`[data-testid="department-option"][data-department="${name}"]`) as
    | HTMLInputElement
    | null;

describe('DepartmentPicker', () => {
  it('lists every assignable department', async () => {
    renderWithProviders(<Harness />);
    await screen.findByTestId('department-picker');
    expect(screen.getAllByTestId('department-option')).toHaveLength(2);
  });

  it('shows the root checked and disabled', async () => {
    renderWithProviders(<Harness />);
    await screen.findByTestId('department-picker');
    expect(option('HQ')!.checked).toBe(true);
    expect(option('HQ')!.disabled).toBe(true);
  });

  it('cannot be made to deselect the root', async () => {
    renderWithProviders(<Harness />);
    await screen.findByTestId('department-picker');
    await userEvent.click(option('HQ')!);
    expect(option('HQ')!.checked).toBe(true);
  });

  it('toggles a non-root department on and off', async () => {
    renderWithProviders(<Harness />);
    await screen.findByTestId('department-picker');

    await userEvent.click(option('HR')!);
    await waitFor(() => expect(screen.getByTestId('selection')).toHaveTextContent('dept-hr'));

    await userEvent.click(option('HR')!);
    await waitFor(() => expect(screen.getByTestId('selection')).toHaveTextContent(''));
  });

  it('reports a load failure instead of rendering an empty list', async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response('{}', { status: 500 }))
    );
    renderWithProviders(<Harness />);
    expect(await screen.findByText(/could not load departments/i)).toBeInTheDocument();
  });
});

describe('withRoot', () => {
  it('adds the root to a selection that omits it', () => {
    expect(withRoot(new Set(['dept-hr']), [ROOT, HR]).sort()).toEqual(['dept-hq', 'dept-hr']);
  });

  it('does not duplicate an already-present root', () => {
    expect(withRoot(new Set(['dept-hq']), [ROOT, HR])).toEqual(['dept-hq']);
  });

  it('survives a response that is not an array', () => {
    // The API could answer with an error envelope; throwing here would blank
    // the whole upload page rather than degrade.
    expect(rootDepartmentId({ detail: 'nope' } as unknown as Department[])).toBeUndefined();
    expect(withRoot(new Set(['dept-hr']), undefined)).toEqual(['dept-hr']);
  });
});
