import { describe, it, expect } from 'vitest';
import { formatBytes, formatDate, cn } from './utils';

describe('Frontend Utils', () => {
  it('formats byte sizes correctly', () => {
    expect(formatBytes(0)).toBe('0 Bytes');
    expect(formatBytes(1024)).toBe('1 KiB');
    expect(formatBytes(1048576)).toBe('1 MiB');
    expect(formatBytes(104857600)).toBe('100 MiB');
  });

  it('formats dates cleanly', () => {
    expect(formatDate(null)).toBe('—');
    expect(formatDate(undefined)).toBe('—');
    const d = new Date('2026-08-27T10:00:00Z');
    expect(formatDate(d.toISOString())).toContain('2026');
  });

  it('merges tailwind classes properly', () => {
    expect(cn('bg-red-500', 'bg-blue-500')).toBe('bg-blue-500');
    expect(cn('px-2 py-1', { 'font-bold': true, 'italic': false })).toBe('px-2 py-1 font-bold');
  });
});
