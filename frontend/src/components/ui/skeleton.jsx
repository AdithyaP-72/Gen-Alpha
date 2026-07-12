import { cn } from '../../lib/utils';

export function Skeleton({ className, ...props }) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />;
}

export function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 px-6 py-12 text-center', className)}>
      {Icon && (
        <div className="mb-1 flex h-10 w-10 items-center justify-center rounded-lg border bg-muted text-subtle">
          <Icon className="h-5 w-5" />
        </div>
      )}
      <p className="text-[13px] font-medium text-foreground">{title}</p>
      {description && <p className="max-w-sm text-xs text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}
