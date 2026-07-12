import React, { useLayoutEffect, useRef, useState } from 'react';
import { cn } from '../../lib/utils';

/** Minimal controlled tabs (no Radix). TabsList renders a sliding solid pill
    behind the active trigger — same language as the header nav. */
export function Tabs({ value, onValueChange, className, children }) {
  return (
    <div className={className} data-value={value}>
      {React.Children.map(children, (child) =>
        React.isValidElement(child)
          ? React.cloneElement(child, { __value: value, __onChange: onValueChange })
          : child,
      )}
    </div>
  );
}

export function TabsList({ className, children, __value, __onChange }) {
  const ref = useRef(null);
  const [pill, setPill] = useState({ left: 0, width: 0, ready: false });

  useLayoutEffect(() => {
    const measure = () => {
      const el = ref.current?.querySelector(`[data-tab="${__value}"]`);
      if (!el) {
        setPill((p) => ({ ...p, ready: false }));
        return;
      }
      setPill({ left: el.offsetLeft, width: el.offsetWidth, ready: true });
    };
    measure();
    const t = setTimeout(measure, 60); // labels carry live counts / fonts settle
    window.addEventListener('resize', measure, { passive: true });
    return () => {
      clearTimeout(t);
      window.removeEventListener('resize', measure);
    };
  }, [__value, children]);

  return (
    <div
      ref={ref}
      role="tablist"
      className={cn(
        'relative inline-flex items-center rounded-full border bg-muted p-1 text-muted-foreground',
        className,
      )}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute bottom-1 top-1 rounded-full bg-primary shadow-card"
        style={{
          left: pill.left,
          width: pill.width,
          opacity: pill.ready ? 1 : 0,
          transition:
            'left 0.3s cubic-bezier(0.4,0,0.2,1), width 0.3s cubic-bezier(0.4,0,0.2,1), opacity 0.2s',
        }}
      />
      {React.Children.map(children, (child) =>
        React.isValidElement(child)
          ? React.cloneElement(child, { __value, __onChange })
          : child,
      )}
    </div>
  );
}

export function TabsTrigger({ value, className, children, __value, __onChange }) {
  const active = __value === value;
  return (
    <button
      role="tab"
      data-tab={value}
      aria-selected={active}
      onClick={() => __onChange?.(value)}
      className={cn(
        'relative z-10 inline-flex h-7 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-3.5 text-[13px] font-medium transition-colors duration-200',
        '[&_svg]:size-3.5',
        active ? 'text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
        className,
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({ value, className, children, __value }) {
  if (__value !== value) return null;
  return <div className={className}>{children}</div>;
}
