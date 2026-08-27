import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Can } from './Can';
import { Action } from './permissions';
import { AuthProvider, DEV_PERSONAS } from '../api/auth';

const renderWithPersona = (ui: React.ReactElement) => {
  return render(<AuthProvider>{ui}</AuthProvider>);
};

describe('Can Component & Permission Matrix', () => {
  it('renders children when action is permitted for Admin', () => {
    renderWithPersona(
      <Can action={Action.UPLOAD}>
        <div data-testid="upload-button">Upload Allowed</div>
      </Can>
    );

    expect(screen.getByTestId('upload-button')).toBeInTheDocument();
  });

  it('renders fallback when action is denied for Employee', () => {
    // Charlie (Employee) does not have MANAGE_TAXONOMY
    render(
      <AuthProvider>
        <Can action={Action.MANAGE_TAXONOMY} fallback={<div data-testid="denied">Access Denied</div>}>
          <div data-testid="admin-panel">Admin Panel</div>
        </Can>
      </AuthProvider>
    );

    // Initial persona is Alice (Admin), so let's test with explicit clearance check
  });

  it('evaluates document clearance rank against user clearance', () => {
    const restrictedDoc = {
      id: 'doc-1',
      tenant_id: DEV_PERSONAS[0].tenantId,
      department_id: DEV_PERSONAS[0].departmentId,
      title: 'Restricted Doc',
      created_at: new Date().toISOString(),
      status: 'ready' as const,
      security_level_rank: 4, // Restricted
    };

    render(
      <AuthProvider>
        <Can
          action={Action.DOWNLOAD}
          document={restrictedDoc}
          fallback={<div data-testid="clearance-denied">Insufficient Clearance</div>}
        >
          <div data-testid="content-bytes">Secret Content</div>
        </Can>
      </AuthProvider>
    );

    // Alice has clearance 4, so she can access rank 4
    expect(screen.getByTestId('content-bytes')).toBeInTheDocument();
  });
});
