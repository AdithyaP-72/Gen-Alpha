import React from 'react';
import { cn } from '../../lib/utils';

export const Table = ({ className, ...props }) => (
  <div className="w-full overflow-x-auto">
    <table className={cn('w-full caption-bottom text-[13px]', className)} {...props} />
  </div>
);

export const TableHeader = ({ className, ...props }) => (
  <thead className={cn('[&_tr]:border-b', className)} {...props} />
);

export const TableBody = ({ className, ...props }) => (
  <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />
);

export const TableRow = ({ className, ...props }) => (
  <tr
    className={cn('border-b transition-colors duration-100 hover:bg-accent', className)}
    {...props}
  />
);

export const TableHead = ({ className, ...props }) => (
  <th
    className={cn(
      'h-9 px-3 text-left align-middle text-[11px] font-medium text-subtle first:pl-5 last:pr-5',
      className,
    )}
    {...props}
  />
);

export const TableCell = ({ className, ...props }) => (
  <td
    className={cn('px-3 py-2.5 align-middle first:pl-5 last:pr-5', className)}
    {...props}
  />
);
