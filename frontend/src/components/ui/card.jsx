import React from 'react';
import { cn } from '../../lib/utils';

export const Card = React.forwardRef(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn('rounded-xl border bg-card shadow-card', className)}
    {...props}
  />
));
Card.displayName = 'Card';

export const CardHeader = ({ className, ...props }) => (
  <div
    className={cn('flex flex-col gap-1 border-b px-5 py-4', className)}
    {...props}
  />
);

export const CardTitle = ({ className, ...props }) => (
  <h3
    className={cn('text-[13px] font-semibold leading-none tracking-[-0.01em]', className)}
    {...props}
  />
);

export const CardDescription = ({ className, ...props }) => (
  <p className={cn('text-xs leading-relaxed text-muted-foreground', className)} {...props} />
);

export const CardContent = ({ className, ...props }) => (
  <div className={cn('p-5', className)} {...props} />
);

export const CardFooter = ({ className, ...props }) => (
  <div className={cn('flex items-center border-t px-5 py-3', className)} {...props} />
);
