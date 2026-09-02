import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DepartmentAdmin } from './DepartmentAdmin';
import { api } from '../../api/client';
import { DepartmentOut } from '../../api/types';
import { renderWithProviders, PERSONA_ADMIN } from '../../test-utils';

const mockDepartments: DepartmentOut[] = [
  {
    id: 'c0000000-0000-0000-0000-000000000011',
    name: 'HQ',
    parent_id: null,
    is_root: true,
    assignable: true,
  },
  {
    id: 'c0000000-0000-0000-0000-000000000012',
    name: 'Engineering',
    parent_id: 'c0000000-0000-0000-0000-000000000011',
    is_root: false,
    assignable: true,
  },
];

describe('DepartmentAdmin', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const renderComponent = () => {
    return renderWithProviders(<DepartmentAdmin />, {
      persona: PERSONA_ADMIN,
    });
  };

  it('renders existing departments with root status', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockDepartments);
    renderComponent();

    expect((await screen.findAllByRole('cell', { name: /HQ/i }))[0]).toBeInTheDocument();
    expect(screen.getByText('Tenant Root')).toBeInTheDocument();
    expect((await screen.findAllByRole('cell', { name: /Engineering/i }))[0]).toBeInTheDocument();
    expect(screen.getByText('Sub-Department')).toBeInTheDocument();
  });

  it('creates a new department and submits to /v1/departments', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockDepartments);
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      id: 'c0000000-0000-0000-0000-000000000013',
      name: 'Legal & Compliance',
      parent_id: 'c0000000-0000-0000-0000-000000000011',
      is_root: false,
      assignable: true,
    });

    renderComponent();

    const user = userEvent.setup();
    const nameInput = await screen.findByLabelText(/department name/i);
    const createButton = screen.getByRole('button', { name: /create department/i });

    await user.type(nameInput, 'Legal & Compliance');
    expect(createButton).toBeEnabled();

    fireEvent.click(createButton);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith('/v1/departments', {
        name: 'Legal & Compliance',
        parent_id: undefined,
      });
    });

    expect(await screen.findByText(/department "Legal & Compliance" created successfully/i)).toBeInTheDocument();
  });

  it('allows specifying a parent department', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockDepartments);
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      id: 'c0000000-0000-0000-0000-000000000014',
      name: 'Security Ops',
      parent_id: 'c0000000-0000-0000-0000-000000000012',
      is_root: false,
      assignable: true,
    });

    renderComponent();

    const user = userEvent.setup();
    const nameInput = await screen.findByLabelText(/department name/i);
    const parentSelect = screen.getByLabelText(/parent department/i);
    const createButton = screen.getByRole('button', { name: /create department/i });

    await user.type(nameInput, 'Security Ops');
    await user.selectOptions(parentSelect, 'c0000000-0000-0000-0000-000000000012');

    fireEvent.click(createButton);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith('/v1/departments', {
        name: 'Security Ops',
        parent_id: 'c0000000-0000-0000-0000-000000000012',
      });
    });
  });
});
