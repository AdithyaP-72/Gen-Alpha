import React from 'react';
import { cn } from '../../lib/utils';

const variants = {
  default:
    'bg-primary text-primary-foreground shadow-card hover:opacity-90 active:opacity-80',
  outline:
    'border border-input bg-card text-foreground shadow-card hover:bg-accent',
  ghost: 'text-secondary-ink hover:bg-accent hover:text-foreground',
  destructive:
    'bg-status-crit text-white shadow-card hover:opacity-90 active:opacity-80',
};

const sizes = {
  default: 'h-9 px-4 text-[13px]',
  sm: 'h-8 px-3 text-[13px]',
  lg: 'h-10 px-5 text-sm',
  icon: 'h-9 w-9',
  'icon-sm': 'h-8 w-8',
};

export const Button = React.forwardRef(
  ({ className, variant = 'default', size = 'default', ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        'inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium',
        'transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50',
        '[&_svg]:size-4 [&_svg]:shrink-0',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = 'Button';
