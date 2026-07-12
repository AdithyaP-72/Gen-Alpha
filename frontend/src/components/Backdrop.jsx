import React from 'react';

/**
 * Ambient backdrop — a fine coordinate grid, topographic contour lines that
 * breathe opacity (no motion sweep), two faint reticles, and a vignette toward
 * the page plane. Fixed, behind everything, non-interactive. Theme-aware via
 * CSS tokens.
 */
function Reticle({ className }) {
  return (
    <svg className={className} width="44" height="44" viewBox="0 0 44 44" fill="none" stroke="var(--border-strong)">
      <circle cx="22" cy="22" r="13" strokeWidth="0.75" />
      <line x1="22" y1="2" x2="22" y2="14" strokeWidth="0.75" />
      <line x1="22" y1="30" x2="22" y2="42" strokeWidth="0.75" />
      <line x1="2" y1="22" x2="14" y2="22" strokeWidth="0.75" />
      <line x1="30" y1="22" x2="42" y2="22" strokeWidth="0.75" />
    </svg>
  );
}

export function Backdrop() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
      style={{ backgroundColor: 'var(--background)' }}
    >
      {/* Fine coordinate grid, fading from the top */}
      <div
        className="absolute inset-0 opacity-60"
        style={{
          backgroundImage:
            'linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)',
          backgroundSize: '64px 64px',
          maskImage: 'radial-gradient(130% 100% at 50% 0%, black 35%, transparent 100%)',
          WebkitMaskImage: 'radial-gradient(130% 100% at 50% 0%, black 35%, transparent 100%)',
        }}
      />

      {/* Topographic contour lines — breathing opacity only */}
      <svg
        className="archive-breathe absolute inset-0 h-full w-full"
        preserveAspectRatio="xMidYMid slice"
        viewBox="0 0 1200 900"
      >
        <g fill="none" stroke="var(--border-strong)" strokeWidth="1">
          {[0, 36, 76, 120, 168, 220, 276, 336, 400].map((d, i) => (
            <path
              key={i}
              d={`M -50 ${240 + d} C 220 ${160 + d}, 420 ${340 + d}, 640 ${280 + d} S 1040 ${180 + d}, 1260 ${300 + d}`}
              opacity={0.32 - i * 0.025}
            />
          ))}
        </g>
      </svg>

      {/* Faint reticles, out of the content column */}
      <Reticle className="absolute left-[6%] top-[44%] opacity-20" />
      <Reticle className="absolute right-[8%] top-[70%] opacity-[0.15]" />

      {/* Vignette toward the page plane keeps content legible */}
      <div
        className="absolute inset-0"
        style={{ background: 'linear-gradient(to bottom, transparent, transparent, var(--background))' }}
      />
    </div>
  );
}
