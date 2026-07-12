import React, { useState } from 'react';
import { Grid3x3 } from 'lucide-react';
import { cn } from '../lib/utils';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { EmptyState } from './ui/skeleton';

/**
 * Diverging heatmap: cool pole (blue) = negative r, warm pole (red) = positive r,
 * neutral gray midpoint at 0. Cell color = |r| mix toward the pole; every cell
 * carries a direct label in text ink so color never works alone.
 */
function cellStyle(r, isDiagonal) {
  if (isDiagonal) return { background: 'var(--muted)' };
  const pole = r >= 0 ? 'var(--chart-pos)' : 'var(--chart-neg)';
  const strength = Math.min(Math.abs(r), 1) * 85; // cap so ink stays readable
  return { background: `color-mix(in oklab, ${pole} ${strength}%, var(--chart-mid))` };
}

function DivergingLegend() {
  return (
    <div className="flex items-center gap-2 text-[10px] text-subtle">
      <span className="tnum">−1</span>
      <div
        className="h-1.5 w-24 rounded-full"
        style={{
          background:
            'linear-gradient(to right, var(--chart-neg), var(--chart-mid) 50%, var(--chart-pos))',
        }}
      />
      <span className="tnum">+1</span>
      <span className="ml-1">daily-PnL correlation</span>
    </div>
  );
}

export function CorrelationCard({ correlation }) {
  const [hover, setHover] = useState(null); // {i, j}
  const { labels = [], matrix = [], insufficient, note } = correlation || {};
  const n = labels.length;

  return (
    <Card className="flex flex-col">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div className="space-y-1">
          <CardTitle>Signal correlation</CardTitle>
          <CardDescription>
            Pearson r between daily PnL series, measured from BRAIN recordsets.
          </CardDescription>
        </div>
        <Grid3x3 className="h-4 w-4 text-subtle" />
      </CardHeader>

      <CardContent className="flex flex-1 flex-col">
        {insufficient || n < 2 ? (
          <EmptyState
            icon={Grid3x3}
            title="Not enough measured PnL"
            description={note || 'Two or more alphas with retrievable PnL recordsets are required.'}
            className="flex-1 py-8"
          />
        ) : (
          <>
            <div
              className="grid gap-0.5"
              style={{ gridTemplateColumns: `minmax(56px,auto) repeat(${n}, minmax(0,1fr))` }}
              onMouseLeave={() => setHover(null)}
              role="table"
              aria-label="Correlation matrix"
            >
              {/* corner */}
              <div />
              {labels.map((l, j) => (
                <div
                  key={`c${j}`}
                  className={cn(
                    'truncate pb-1 text-center font-mono text-[10px] text-subtle',
                    hover?.j === j && 'text-foreground',
                  )}
                >
                  {l}
                </div>
              ))}
              {matrix.map((row, i) => (
                <React.Fragment key={`r${i}`}>
                  <div
                    className={cn(
                      'flex items-center truncate pr-2 font-mono text-[10px] text-subtle',
                      hover?.i === i && 'text-foreground',
                    )}
                  >
                    {labels[i]}
                  </div>
                  {row.map((v, j) => {
                    const diag = i === j;
                    const active = hover && (hover.i === i || hover.j === j);
                    return (
                      <div
                        key={j}
                        role="cell"
                        onMouseEnter={() => setHover({ i, j })}
                        title={diag ? undefined : `${labels[i]} × ${labels[j]}: r = ${v.toFixed(2)}`}
                        className={cn(
                          'tnum flex h-9 items-center justify-center rounded-[4px] text-[11px] transition-[box-shadow] duration-100',
                          diag ? 'text-subtle' : 'text-foreground',
                          active && !diag && 'ring-1 ring-inset ring-border-strong',
                          hover?.i === i && hover?.j === j && !diag && 'ring-2 ring-ring',
                        )}
                        style={cellStyle(v, diag)}
                      >
                        {diag ? '—' : v.toFixed(2)}
                      </div>
                    );
                  })}
                </React.Fragment>
              ))}
            </div>
            <div className="mt-4 flex items-center justify-between">
              <DivergingLegend />
              <span className="text-[10px] text-subtle">lower |r| → more orthogonal book</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
