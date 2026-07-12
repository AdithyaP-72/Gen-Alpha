import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Moon, Play, Square, Sun } from 'lucide-react';
import { cn } from '../lib/utils';
import { Button } from './ui/button';

const GithubIcon = (props) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    {...props}
  >
    <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5a5.4 5.4 0 0 0-1-3.5 5.4 5.4 0 0 0 0-3.5s-1 0-3 1.5a13.4 13.4 0 0 0-7 0C6 2 5 2 5 2a5.4 5.4 0 0 0 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.4.5-.7 1-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
    <path d="M9 18c-4.51 2-5-2-7-2" />
  </svg>
);

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid h-7 w-7 place-items-center rounded-md bg-primary text-primary-foreground">
        {/* Italic serif alpha reads unambiguously as a mathematical α */}
        <span
          className="text-[17px] font-semibold italic leading-none"
          style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}
        >
          α
        </span>
      </div>
      <div className="leading-tight">
        <span className="font-display block text-[17px] font-extrabold tracking-[-0.02em]">
          Gen-Alpha
        </span>
        <span className="block text-[10px] tracking-[0.02em] text-subtle">Research terminal</span>
      </div>
    </div>
  );
}

/** Sliding-highlight pill nav — a solid neutral highlight that animates between
    items. High contrast, no glow. */
function PillNav({ tab, setTab, items }) {
  const containerRef = useRef(null);
  const [pill, setPill] = useState({ left: 0, width: 0, ready: false });

  useLayoutEffect(() => {
    const measure = () => {
      const container = containerRef.current;
      if (!container) return;
      const el = container.querySelector(`[data-tab="${tab}"]`);
      if (!el) return;
      setPill({ left: el.offsetLeft, width: el.offsetWidth, ready: true });
    };
    measure();
    const t = setTimeout(measure, 60); // re-measure after fonts settle
    window.addEventListener('resize', measure, { passive: true });
    return () => {
      clearTimeout(t);
      window.removeEventListener('resize', measure);
    };
  }, [tab]);

  return (
    <div
      ref={containerRef}
      className="relative flex items-center rounded-full border bg-muted p-1"
      role="tablist"
      aria-label="Primary"
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
      {items.map((item) => (
        <button
          key={item.id}
          data-tab={item.id}
          role="tab"
          aria-selected={tab === item.id}
          onClick={() => setTab(item.id)}
          className={cn(
            'relative z-10 rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors duration-200',
            tab === item.id
              ? 'text-primary-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function StatusPill({ running, statusMsg, onClick }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'hidden items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors sm:flex',
        'hover:bg-accent',
        running ? 'text-foreground' : 'text-muted-foreground',
      )}
      title="Open pipeline monitor"
    >
      <span className="relative flex h-2 w-2">
        {running && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-good opacity-60" />
        )}
        <span
          className={cn(
            'relative inline-flex h-2 w-2 rounded-full',
            running ? 'bg-status-good' : 'bg-axis',
          )}
        />
      </span>
      <span className="max-w-56 truncate">{statusMsg}</span>
    </button>
  );
}

export function Header({ tab, setTab, running, statusMsg, onTrigger, onOpenPipeline, theme, onToggleTheme }) {
  const navItems = [
    { id: 'overview', label: 'Overview' },
    { id: 'library', label: 'Library' },
    { id: 'pipeline', label: 'Pipeline' },
  ];

  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-6">
          <Logo />
          <div className="hidden md:block">
            <PillNav tab={tab} setTab={setTab} items={navItems} />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <StatusPill running={running} statusMsg={statusMsg} onClick={onOpenPipeline} />
          <Button
            size="sm"
            variant={running ? 'outline' : 'default'}
            onClick={onTrigger}
            className={cn(running && 'text-status-crit hover:text-status-crit')}
          >
            {running ? <Square className="fill-current" /> : <Play className="fill-current" />}
            {running ? 'Stop' : 'Run pipeline'}
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={onToggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? <Sun /> : <Moon />}
          </Button>
          <a
            href="https://github.com/AdithyaP-72/Gen-Alpha"
            target="_blank"
            rel="noreferrer"
            aria-label="GitHub repository"
            className="hidden h-8 w-8 items-center justify-center rounded-md text-secondary-ink transition-colors hover:bg-accent hover:text-foreground sm:flex"
          >
            <GithubIcon className="h-4 w-4" />
          </a>
        </div>
      </div>

      {/* Mobile nav pill row */}
      <div className="border-t border-border/60 px-4 py-2 md:hidden">
        <PillNav tab={tab} setTab={setTab} items={navItems} />
      </div>
    </header>
  );
}
