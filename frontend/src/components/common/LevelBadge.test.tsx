import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LevelBadge } from './LevelBadge';

describe('LevelBadge Component', () => {
  it('renders Public badge correctly', () => {
    render(<LevelBadge level="public" />);
    expect(screen.getByText('Public')).toBeInTheDocument();
  });

  it('renders Internal badge correctly', () => {
    render(<LevelBadge level="internal" />);
    expect(screen.getByText('Internal')).toBeInTheDocument();
  });

  it('renders Confidential badge correctly', () => {
    render(<LevelBadge level="confidential" />);
    expect(screen.getByText('Confidential')).toBeInTheDocument();
  });

  it('renders Restricted badge with rank fallback', () => {
    render(<LevelBadge rank={4} />);
    expect(screen.getByText('Restricted')).toBeInTheDocument();
  });
});
