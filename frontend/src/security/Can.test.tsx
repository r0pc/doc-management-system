import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Can } from './Can';
import { Action } from './permissions';
import { AuthProvider, DemoAccount } from '../api/auth';
import { setAuthToken } from '../api/client';
import {
  makeDevToken,
  PERSONA_ADMIN,
  PERSONA_EMPLOYEE,
  PERSONA_VIEWER,
} from '../test-utils';

/**
 * `<Can>` gates chrome on role and clearance. Every check here is cosmetic
 * (#33) — the API re-authorizes each request — so what is being asserted is
 * that a user is not SHOWN a control that will only ever be refused.
 *
 * Each case seeds a session explicitly. These tests used to render a bare
 * `<AuthProvider>` and lean on it signing itself in as a clearance-4 admin,
 * which meant they asserted the auto-login defect rather than the gate: with no
 * session the app now renders the login page, so "no token" must mean "no
 * access", not "administrator".
 */

const signedInAs = (account: DemoAccount | null, ui: React.ReactElement) => {
  setAuthToken(account ? makeDevToken(account) : null);
  return render(<AuthProvider demoLoginEnabled={false}>{ui}</AuthProvider>);
};

const restrictedDoc = {
  id: 'doc-1',
  document_id: 'doc-1',
  tenant_id: PERSONA_ADMIN.tenantId,
  department_id: PERSONA_ADMIN.departmentId,
  filename: 'Restricted Doc',
  created_at: new Date().toISOString(),
  status: 'ready' as const,
  level: 'restricted',
  doc_type: 'unknown',
};

beforeEach(() => {
  setAuthToken(null);
});

describe('Can — role gating', () => {
  it('renders children when the action is permitted for the role', () => {
    signedInAs(
      PERSONA_ADMIN,
      <Can action={Action.UPLOAD}>
        <div data-testid="upload-button">Upload Allowed</div>
      </Can>
    );
    expect(screen.getByTestId('upload-button')).toBeInTheDocument();
  });

  it('renders the fallback when the action is denied for the role', () => {
    // An employee holds no taxonomy-management grant.
    signedInAs(
      PERSONA_EMPLOYEE,
      <Can
        action={Action.MANAGE_TAXONOMY}
        fallback={<div data-testid="denied">Access Denied</div>}
      >
        <div data-testid="admin-panel">Admin Panel</div>
      </Can>
    );
    expect(screen.getByTestId('denied')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-panel')).not.toBeInTheDocument();
  });
});

describe('Can — clearance gating', () => {
  it('admits a document at or below the user clearance', () => {
    signedInAs(
      PERSONA_ADMIN,
      <Can
        action={Action.DOWNLOAD}
        document={restrictedDoc}
        fallback={<div data-testid="clearance-denied">Insufficient Clearance</div>}
      >
        <div data-testid="content-bytes">Secret Content</div>
      </Can>
    );
    // Clearance 4 reaches a Restricted (rank 4) document.
    expect(screen.getByTestId('content-bytes')).toBeInTheDocument();
  });

  it('refuses a document above the user clearance', () => {
    signedInAs(
      PERSONA_VIEWER,
      <Can
        action={Action.DOWNLOAD}
        document={restrictedDoc}
        fallback={<div data-testid="clearance-denied">Insufficient Clearance</div>}
      >
        <div data-testid="content-bytes">Secret Content</div>
      </Can>
    );
    // Clearance 1 must not be offered a Restricted document.
    expect(screen.getByTestId('clearance-denied')).toBeInTheDocument();
    expect(screen.queryByTestId('content-bytes')).not.toBeInTheDocument();
  });
});

describe('Can — no session', () => {
  it('grants nothing when there is no token', () => {
    signedInAs(
      null,
      <Can action={Action.UPLOAD} fallback={<div data-testid="denied">Access Denied</div>}>
        <div data-testid="upload-button">Upload Allowed</div>
      </Can>
    );
    expect(screen.queryByTestId('upload-button')).not.toBeInTheDocument();
    expect(screen.getByTestId('denied')).toBeInTheDocument();
  });
});
