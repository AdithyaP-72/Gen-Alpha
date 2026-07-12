import React from 'react';
import { cn } from '../../lib/utils';

const variants = {
  default: 'border-transparent bg-muted text-secondary-ink',
  outline: 'border-border-strong text-secondary-ink',
  info: 'border-transparent bg-[color-mix(in_oklab,var(--chart-1)_12%,transparent)] text-chart-1-strong',
  success:
    'border-transparent bg-[color-mix(in_oklab,var(--status-good)_12%,transparent)] text-status-good-ink',
  warning:
    'border-transparent bg-[color-mix(in_oklab,var(--status-warn-dot)_14%,transparent)] text-status-warn',
  danger:
    'border-transparent bg-[color-mix(in_oklab,var(--status-crit)_12%,transparent)] text-status-crit',
};

export function Badge({ className, variant = 'default', ...props }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-4',
        '[&_svg]:size-3',
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
