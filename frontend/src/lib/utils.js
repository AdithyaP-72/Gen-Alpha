import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export const fmt2 = (v) => (v == null ? '—' : Number(v).toFixed(2));
export const fmtPct = (v) => (v == null ? '—' : (Number(v) * 100).toFixed(1) + '%');
export const fmtMoney = (v) =>
  v >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e7 ? 1 : 2)}M` : `$${Math.round(v).toLocaleString()}`;
