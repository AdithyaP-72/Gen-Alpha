import React, { useMemo, useState } from 'react';
import { TrendingUp } from 'lucide-react';
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { fmtMoney } from '../lib/utils';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 shadow-raised">
      <p className="text-[10px] font-medium text-subtle">{label}</p>
      <p className="tnum text-[13px] font-semibold">{fmtMoney(payload[0].value)}</p>
    </div>
  );
}

/**
 * Compounds the MEASURED portfolio annual return over 5 years.
 * A projection, labeled as such — never a synthetic backtest curve.
 */
export function ProjectionCard({ portfolio }) {
  const [budget, setBudget] = useState(10_000_000);
  const annReturn = portfolio?.ann_return ?? 0;

  const data = useMemo(() => {
    const pts = [];
    let v = budget;
    pts.push({ label: 'Now', value: Math.round(v) });
    for (let q = 1; q <= 20; q++) {
      v *= 1 + annReturn / 4;
      pts.push({ label: `Y${Math.ceil(q / 4)} Q${((q - 1) % 4) + 1}`, value: Math.round(v) });
    }
    return pts;
  }, [budget, annReturn]);

  const finalValue = data[data.length - 1]?.value ?? budget;
  const cumPct = ((finalValue / budget - 1) * 100).toFixed(1);
  const fillPct = ((budget - 1_000_000) / (50_000_000 - 1_000_000)) * 100;

  return (
    <Card className="flex flex-col">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div className="space-y-1">
          <CardTitle>5-year yield projection</CardTitle>
          <CardDescription>
            {portfolio?.measured
              ? 'Compounded from the inverse-volatility portfolio’s measured PnL.'
              : portfolio?.note || 'Compounded from measured per-alpha IS returns.'}
          </CardDescription>
        </div>
        <TrendingUp className="h-4 w-4 text-subtle" />
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-[11px] font-medium text-subtle">
              Projected value
            </p>
            <p className="tnum text-[26px] font-semibold leading-8 tracking-[-0.02em]">
              {fmtMoney(finalValue)}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              <span className={annReturn >= 0 ? 'text-status-good-ink' : 'text-status-crit'}>
                {cumPct >= 0 ? '+' : ''}
                {cumPct}%
              </span>{' '}
              cumulative from {(annReturn * 100).toFixed(1)}%/yr measured
              {portfolio?.sharpe != null && <> · portfolio Sharpe {portfolio.sharpe}</>}
            </p>
          </div>
          <div className="w-full max-w-56">
            <div className="mb-1.5 flex items-center justify-between text-[11px]">
              <span className="text-subtle">Initial capital</span>
              <span className="tnum font-medium">{fmtMoney(budget)}</span>
            </div>
            <input
              type="range"
              className="slider"
              min={1_000_000}
              max={50_000_000}
              step={1_000_000}
              value={budget}
              style={{ '--fill': `${fillPct}%` }}
              onChange={(e) => setBudget(Number(e.target.value))}
              aria-label="Initial capital"
            />
          </div>
        </div>

        <div className="h-44 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
              <defs>
                <linearGradient id="projFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.16} />
                  <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="0" vertical={false} />
              <XAxis
                dataKey="label"
                stroke="var(--axis)"
                tick={{ fill: 'var(--subtle)', fontSize: 10 }}
                tickLine={false}
                axisLine={{ stroke: 'var(--axis)' }}
                interval={3}
              />
              <YAxis
                stroke="var(--axis)"
                tick={{ fill: 'var(--subtle)', fontSize: 10 }}
                tickFormatter={(v) => fmtMoney(v)}
                tickLine={false}
                axisLine={false}
                width={52}
              />
              <Tooltip
                content={<ChartTooltip />}
                cursor={{ stroke: 'var(--axis)', strokeDasharray: '3 3' }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="var(--chart-1)"
                strokeWidth={2}
                fill="url(#projFill)"
                dot={false}
                activeDot={{ r: 4, fill: 'var(--chart-1)', stroke: 'var(--card)', strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <p className="text-[10px] leading-relaxed text-subtle">
          Projection, not a guarantee — extrapolates the measured in-sample rate and ignores decay,
          costs, and capacity.
        </p>
      </CardContent>
    </Card>
  );
}
