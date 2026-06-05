#!/usr/bin/env python3
"""
DFR Dashboard Generator
Regenerates DFR_Dashboard_2026.html from a CSV export.

Usage:
    py update_dashboard.py
    py update_dashboard.py --csv path/to/NewExport.csv
    py update_dashboard.py --csv NewExport.csv --out MyDashboard.html

The 'Most Common Request' analysis is read from insights.json and must be
updated manually (with AI assistance). All other metrics are fully automatic.
"""

import csv
import json
import sys
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DEFAULT_CSV = SCRIPT_DIR / 'DFRF2026YTD.csv'
DEFAULT_OUT = SCRIPT_DIR / 'DFR_Dashboard_2026.html'
INSIGHTS_FILE = SCRIPT_DIR / 'insights.json'

DATE_FMT = '%d/%b/%y %I:%M %p'
ALL_MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

# ── Category rules (evaluated in order; first match wins) ─────────────────────
CATEGORY_RULES = [
    ('BP Report',            lambda t: 'burst pressure' in t or 'bp report' in t or (' bp ' in t and 'report' in t) or 'bp calc' in t),
    ('AIA Report',           lambda t: 'aia' in t),
    ('LAS File Export',      lambda t: 'las file' in t or '.las' in t),
    ('Portal Upload/Update', lambda t: 'portal' in t and ('upload' in t or 'add' in t or 'update' in t)),
    ('Visualization/Views',  lambda t: 'visual' in t or 'vid' in t or ('view' in t and 'connection' in t) or 'video' in t or 'animation' in t),
    ('Rerun/Reprocess',      lambda t: 'rerun' in t or 're-run' in t or 'reprocess' in t or 're-process' in t),
    ('Excel Export',         lambda t: 'excel' in t or '.xlsx' in t),
    ('CSV Export',           lambda t: 'csv' in t),
    ('PDF Export',           lambda t: 'pdf' in t),
    ('Correction/Fix',       lambda t: 'correct' in t or 'fix' in t),
    ('Report Generation',    lambda t: 'report' in t),
    ('Data Export',          lambda t: 'export' in t or 'download' in t),
    ('Other',                lambda t: True),
]

PALETTE       = ['#f97316','#f59e0b','#ef4444','#fb923c','#a78bfa','#34d399',
                 '#fbbf24','#ea580c','#60a5fa','#f43f5e','#4ade80','#d97706','#e879f9']
Q_HUE_COLORS  = ['#f97316','#f59e0b','#ea580c','#fbbf24','#fb923c','#d97706',
                 '#c2410c','#fde68a']

# ── Data loading ──────────────────────────────────────────────────────────────

def _categorize(row: dict) -> str:
    text = (row.get('Summary', '') + ' ' + row.get('Description', '')).lower()
    for name, check in CATEGORY_RULES:
        if check(text):
            return name
    return 'Other'


def _parse(s: str):
    try:
        return datetime.strptime(s.strip(), DATE_FMT)
    except Exception:
        return None


def load_rows(csv_path: Path) -> list[dict]:
    rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for raw in reader:
            c = _parse(raw.get('Created', ''))
            u = _parse(raw.get('Updated', ''))
            days = round((u - c).total_seconds() / 86400, 1) if c and u else 0.0
            q_num = (c.month - 1) // 3 + 1 if c else 0
            rows.append({
                'key':      raw.get('Issue key', ''),
                'summary':  raw.get('Summary', ''),
                'assignee': raw.get('Assignee', '').strip() or 'Unassigned',
                'reporter': raw.get('Reporter', '').strip() or 'Unknown',
                'priority': raw.get('Priority', ''),
                'status':   raw.get('Status', ''),
                'created':  c,
                'days':     days,
                'q_num':    q_num,
                'quarter':  f'Q{q_num}' if q_num else 'Unknown',
                'year':     c.year if c else 0,
                'month':    c.month if c else 0,
                'category': _categorize(raw),
            })
    return rows

# ── Metrics computation ───────────────────────────────────────────────────────

def _bucket(d: float) -> str:
    if d <= 1:  return '0-1 day'
    if d <= 3:  return '1-3 days'
    if d <= 7:  return '3-7 days'
    if d <= 14: return '1-2 weeks'
    if d <= 30: return '2-4 weeks'
    return '> 1 month'


def compute(rows: list[dict]) -> dict:
    valid = [r for r in rows if r['year'] > 0]
    if not valid:
        raise ValueError('No valid rows found — check date format in CSV.')

    total = len(valid)

    # Detect all (year, q_num) combos in chronological order
    q_keys = sorted(set((r['year'], r['q_num']) for r in valid if r['q_num'] > 0))

    # Category totals
    cat_ctr = Counter(r['category'] for r in valid)
    cat_labels = [k for k, _ in cat_ctr.most_common()]

    # Assignees
    asgn_ctr   = Counter(r['assignee'] for r in valid)
    asgn_days  = defaultdict(list)
    for r in valid:
        asgn_days[r['assignee']].append(r['days'])
    top_asgn = asgn_ctr.most_common(10)

    # Reporters
    rep_ctr  = Counter(r['reporter'] for r in valid)
    top_rep  = rep_ctr.most_common(12)

    # Priority
    prio_ctr = Counter(r['priority'] for r in valid)

    # Resolution buckets
    bucket_order = ['0-1 day','1-3 days','3-7 days','1-2 weeks','2-4 weeks','> 1 month']
    bucket_ctr   = Counter(_bucket(r['days']) for r in valid)

    # Monthly series across entire data range
    all_ym = sorted(set((r['year'], r['month']) for r in valid))
    monthly_ctr = Counter((r['year'], r['month']) for r in valid)

    # Per-quarter metrics
    quarters: dict[str, dict] = {}
    for year, q_num in q_keys:
        q_rows  = [r for r in valid if r['year'] == year and r['q_num'] == q_num]
        q_label = f'Q{q_num}'
        q_months_nums = list(range((q_num - 1) * 3 + 1, (q_num - 1) * 3 + 4))
        month_ctr     = Counter(r['month'] for r in q_rows)

        avg_days   = round(sum(r['days'] for r in q_rows) / len(q_rows), 1) if q_rows else 0.0
        done       = sum(1 for r in q_rows if r['status'] == 'Done')
        cancelled  = sum(1 for r in q_rows if r['status'] == 'Cancelled')
        peak_m_num = max(month_ctr, key=month_ctr.get) if month_ctr else q_months_nums[0]
        q_cat_ctr  = Counter(r['category'] for r in q_rows)
        top_cat    = q_cat_ctr.most_common(1)[0] if q_cat_ctr else ('Unknown', 0)

        quarters[q_label] = {
            'year':           year,
            'q_num':          q_num,
            'label':          q_label,
            'count':          len(q_rows),
            'avg_days':       avg_days,
            'done':           done,
            'cancelled':      cancelled,
            'completion_pct': round(done / len(q_rows) * 100, 1) if q_rows else 0,
            'months':         [ALL_MONTHS[m - 1] for m in q_months_nums],
            'monthly_counts': [month_ctr.get(m, 0) for m in q_months_nums],
            'peak_month':     ALL_MONTHS[peak_m_num - 1],
            'peak_count':     month_ctr.get(peak_m_num, 0),
            'top_cat':        top_cat[0],
            'top_cat_count':  top_cat[1],
            'top_cat_pct':    round(top_cat[1] / len(q_rows) * 100) if q_rows else 0,
            'cat_ctr':        q_cat_ctr,
        }

    done_all      = sum(1 for r in valid if r['status'] == 'Done')
    cancelled_all = sum(1 for r in valid if r['status'] == 'Cancelled')
    avg_days_all  = round(sum(r['days'] for r in valid) / total, 1)
    q_order       = [f'Q{q}' for _, q in q_keys]

    return {
        'total':           total,
        'avg_days':        avg_days_all,
        'done':            done_all,
        'cancelled':       cancelled_all,
        'completion_pct':  round(done_all / total * 100, 1),
        'quarters':        quarters,
        'q_order':         q_order,
        'cat_labels':      cat_labels,
        'cat_values':      [cat_ctr[c] for c in cat_labels],
        'monthly_labels':  [ALL_MONTHS[m - 1] for _, m in all_ym],
        'monthly_values':  [monthly_ctr[(y, m)] for y, m in all_ym],
        'monthly_qs':      [f'Q{(m-1)//3+1}' for _, m in all_ym],
        'top_asgn_labels': [a[0] for a in top_asgn],
        'top_asgn_counts': [a[1] for a in top_asgn],
        'top_asgn_avgdays':[round(sum(asgn_days[a[0]]) / len(asgn_days[a[0]]), 1) for a in top_asgn],
        'rep_labels':      [r[0] for r in top_rep],
        'rep_values':      [r[1] for r in top_rep],
        'prio_labels':     ['Highest','High','Medium','Low','Lowest'],
        'prio_values':     [prio_ctr.get(p, 0) for p in ['Highest','High','Medium','Low','Lowest']],
        'bucket_labels':   bucket_order,
        'bucket_values':   [bucket_ctr.get(b, 0) for b in bucket_order],
    }

# ── HTML generation helpers ───────────────────────────────────────────────────

def _j(v) -> str:
    """JSON-encode for embedding in JS."""
    return json.dumps(v, ensure_ascii=False)


def _q_color(q_num: int) -> str:
    return Q_HUE_COLORS[(q_num - 1) % len(Q_HUE_COLORS)]


def _fmt_pct(n: float) -> str:
    return f'{n:.0f}%'


def _gen_kpi(label: str, value: str, sub: str, color: str) -> str:
    return f'''
        <div class="kpi" style="--kpi-color:{color}">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value">{value}</div>
          <div class="kpi-sub">{sub}</div>
        </div>'''


def _gen_overall_kpis(m: dict) -> str:
    q_order = m['q_order']
    q_parts = ' · '.join(
        f'<span style="color:{_q_color(m["quarters"][q]["q_num"])}">{q}={m["quarters"][q]["count"]}</span>'
        for q in q_order
    )
    # Speed improvement note
    speed_note = ''
    if len(q_order) >= 2:
        q_first = m['quarters'][q_order[0]]
        q_last  = m['quarters'][q_order[-1]]
        if q_first['avg_days'] > 0:
            delta_pct = round((q_first['avg_days'] - q_last['avg_days']) / q_first['avg_days'] * 100)
            faster = q_last['avg_days'] < q_first['avg_days']
            arrow = '↑' if faster else '↓'
            desc  = 'faster' if faster else 'slower'
            speed_note = f'''
        <div class="kpi" style="--kpi-color:#29c48a">
          <div class="kpi-label">{q_order[-1]} vs {q_order[0]} Speed</div>
          <div class="kpi-value">{arrow}{abs(delta_pct)}<span style="font-size:16px">%</span></div>
          <div class="kpi-sub">{q_last["avg_days"]}d vs {q_first["avg_days"]}d — {desc}</div>
        </div>'''

    return f'''
      <div class="kpi-grid">
        {_gen_kpi("Total Tickets", str(m["total"]), "YTD total", "#f97316")}
        {_gen_kpi("Completion Rate", f'{m["completion_pct"]:.0f}<span style=\"font-size:18px\">%</span>',
                  f'{m["done"]} Done · {m["cancelled"]} Cancelled', "#29c48a")}
        {_gen_kpi("Avg Resolution", f'{m["avg_days"]}<span style="font-size:16px">d</span>',
                  "Created → Last Updated", "#f7c84f")}
        {''.join(_gen_kpi(q, str(m["quarters"][q]["count"]),
                           f'{m["quarters"][q]["months"][0]}–{m["quarters"][q]["months"][-1]} · {m["quarters"][q]["completion_pct"]}% done',
                           _q_color(m["quarters"][q]["q_num"]))
                 for q in q_order)}
        {speed_note}
      </div>'''


def _gen_q_kpis(qd: dict) -> str:
    color = _q_color(qd['q_num'])
    total_pct = ''
    return f'''
      <div class="kpi-grid">
        {_gen_kpi(f'{qd["label"]} Tickets', str(qd["count"]), f'{qd["months"][0]} · {qd["months"][1]} · {qd["months"][2]}', color)}
        {_gen_kpi("Avg Resolution", f'{qd["avg_days"]}<span style="font-size:16px">d</span>', "Created → Last Updated", "#f7c84f")}
        {_gen_kpi("Completion Rate", f'{qd["completion_pct"]:.0f}<span style="font-size:16px">%</span>',
                  f'{qd["done"]} Done · {qd["cancelled"]} Cancelled', "#29c48a")}
        {_gen_kpi("Peak Month", qd["peak_month"], f'{qd["peak_count"]} tickets', color)}
        {_gen_kpi("Top Request", qd["top_cat"].split("/")[0], f'{qd["top_cat_count"]} tickets ({qd["top_cat_pct"]}%)', "#a78bfa")}
      </div>'''


def _gen_cat_table_rows(qd: dict) -> str:
    rows_html = ''
    total = qd['count']
    for cat, cnt in qd['cat_ctr'].most_common():
        pct = round(cnt / total * 100) if total else 0
        rows_html += f'<tr><td>{cat}</td><td style="color:{_q_color(qd["q_num"])};font-weight:600">{cnt}</td><td>{pct}%</td></tr>\n'
    return rows_html


def _gen_comparison_table(m: dict) -> str:
    q_order = m['q_order']
    if len(q_order) < 2:
        return '<p style="color:var(--muted);font-size:13px">Comparison available once 2+ quarters are present.</p>'

    header_cells = '<th>Metric</th>' + ''.join(f'<th>{q}</th>' for q in q_order) + '<th>Trend</th>'

    def row(label, vals, trend=''):
        cells = ''.join(
            '<td style="color:{};font-weight:600">{}</td>'.format(_q_color(m['quarters'][q]['q_num']), v)
            for q, v in zip(q_order, vals)
        )
        return f'<tr><td>{label}</td>{cells}<td>{trend}</td></tr>'

    counts  = [str(m['quarters'][q]['count']) for q in q_order]
    avgs    = [f'{m["quarters"][q]["avg_days"]}d' for q in q_order]
    tops    = [m['quarters'][q]['top_cat'].split('/')[0] for q in q_order]
    peaks   = [f'{m["quarters"][q]["peak_month"]} ({m["quarters"][q]["peak_count"]})' for q in q_order]
    comps   = [f'{m["quarters"][q]["completion_pct"]}%' for q in q_order]

    # Trend: compare last vs first
    q_first = m['quarters'][q_order[0]]
    q_last  = m['quarters'][q_order[-1]]
    cnt_trend  = ('▼' if q_last['count'] < q_first['count'] else '▲') + f' {abs(q_last["count"]-q_first["count"])} tickets'
    speed_chg  = round((q_first['avg_days'] - q_last['avg_days']) / q_first['avg_days'] * 100) if q_first['avg_days'] else 0
    speed_cls  = 'trend-up' if speed_chg > 0 else 'trend-dn'
    speed_word = 'faster' if speed_chg > 0 else 'slower'
    speed_html = f'<span class="{speed_cls}">{abs(speed_chg)}% {speed_word} ({q_order[-1]} vs {q_order[0]})</span>'

    return f'''
      <div class="table-wrap">
        <table class="q-table">
          <thead><tr>{header_cells}</tr></thead>
          <tbody>
            {row("Total Tickets", counts, cnt_trend)}
            {row("Avg Resolution", avgs, speed_html)}
            {row("Top Request Type", tops)}
            {row("Peak Month", peaks)}
            {row("Completion Rate", comps)}
          </tbody>
        </table>
      </div>'''


def _gen_cat_bars_js(m: dict) -> str:
    """Generates the JS that builds the stacked category bars."""
    q_order = m['q_order']
    cat_labels = m['cat_labels']
    lines = ['const catData = ' + json.dumps({
        'labels': cat_labels,
        'totals': m['cat_values'],
        'quarters': {q: [m['quarters'][q]['cat_ctr'].get(c, 0) for c in cat_labels] for q in q_order},
        'q_colors': {q: _q_color(m['quarters'][q]['q_num']) for q in q_order},
    }) + ';']
    return '\n'.join(lines)


def _gen_js_data(m: dict) -> str:
    q_order = m['q_order']
    q_colors_map = {q: _q_color(m['quarters'][q]['q_num']) for q in q_order}

    # Per-quarter chart data for individual panels
    q_chart_data = {}
    for q in q_order:
        qd = m['quarters'][q]
        non_zero = [(c, v) for c, v in qd['cat_ctr'].most_common() if v > 0]
        q_chart_data[q] = {
            'monthly_labels': qd['months'],
            'monthly_counts': qd['monthly_counts'],
            'cat_labels': [x[0] for x in non_zero],
            'cat_values': [x[1] for x in non_zero],
            'color': _q_color(qd['q_num']),
        }

    return f'''
const M = {{
  total: {m['total']},
  avgDays: {m['avg_days']},
  months: {_j(m['monthly_labels'])},
  monthlyValues: {_j(m['monthly_values'])},
  monthlyQs: {_j(m['monthly_qs'])},
  catLabels: {_j(m['cat_labels'])},
  catValues: {_j(m['cat_values'])},
  asgnLabels: {_j(m['top_asgn_labels'])},
  asgnCounts: {_j(m['top_asgn_counts'])},
  asgnAvgDays: {_j(m['top_asgn_avgdays'])},
  repLabels: {_j(m['rep_labels'])},
  repValues: {_j(m['rep_values'])},
  prioLabels: {_j(m['prio_labels'])},
  prioValues: {_j(m['prio_values'])},
  bucketLabels: {_j(m['bucket_labels'])},
  bucketValues: {_j(m['bucket_values'])},
  qOrder: {_j(q_order)},
  qColors: {_j(q_colors_map)},
  qChartData: {_j(q_chart_data)},
}};
{_gen_cat_bars_js(m)}'''


def _gen_q_panel(q: str, m: dict) -> str:
    qd     = m['quarters'][q]
    color  = _q_color(qd['q_num'])
    q_note = ''
    return f'''
  <div id="panel-{q}" class="q-panel">
    <div class="section">
      <div class="section-title">{q} Summary — {qd["months"][0]} to {qd["months"][2]} {qd["year"]}</div>
      {_gen_q_kpis(qd)}
    </div>
    <div class="section">
      <div class="section-title">{q} Monthly Breakdown &amp; Categories</div>
      <div class="chart-grid">
        <div class="chart-card">
          <h3>Monthly Tickets — {q}</h3>
          <div class="chart-wrap chart-h-sm">
            <canvas id="{q}-monthly"></canvas>
          </div>
        </div>
        <div class="chart-card">
          <h3>Request Categories — {q}</h3>
          <div class="chart-wrap chart-h-sm">
            <canvas id="{q}-cats"></canvas>
          </div>
        </div>
      </div>
    </div>
    <div class="section">
      <div class="section-title">{q} Category Breakdown</div>
      <div class="chart-card">
        <div class="table-wrap">
          <table class="q-table">
            <thead><tr><th>Category</th><th>Count</th><th>% of {q}</th></tr></thead>
            <tbody>{_gen_cat_table_rows(qd)}</tbody>
          </table>
        </div>
      </div>
    </div>
  </div>'''


# ── Full HTML assembly ────────────────────────────────────────────────────────

CSS = r"""
  /* ── Dark theme (default) — orange on charcoal ───────────────────────────── */
  :root {
    --bg: #111111; --surface: #1c1c1c; --surface2: #272727;
    --border: #3a3a3a; --accent: #f97316; --green: #22c55e;
    --yellow: #f97316; --red: #ef4444; --text: #ffffff; --muted: #c0c0c0;
    --radius: 12px; --card-sep: rgba(255,255,255,.08);
    color-scheme: dark;
  }
  /* ── Light theme: OS default (no explicit override) ───────────────────────── */
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
      --bg: #dcdcdc; --surface: #f2f2f2; --surface2: #e8e8e8;
      --border: #c4c4c4; --accent: #ea580c; --text: #111111; --muted: #555555;
      --card-sep: rgba(0,0,0,.12);
      color-scheme: light;
    }
  }
  /* ── Explicit overrides ───────────────────────────────────────────────────── */
  :root[data-theme="light"] {
    --bg: #dcdcdc; --surface: #f2f2f2; --surface2: #e8e8e8;
    --border: #c4c4c4; --accent: #ea580c; --text: #111111; --muted: #555555;
    --card-sep: rgba(0,0,0,.12);
    color-scheme: light;
  }
  :root[data-theme="dark"] {
    --bg: #111111; --surface: #1c1c1c; --surface2: #272727;
    --border: #3a3a3a; --text: #ffffff; --muted: #c0c0c0;
    --card-sep: rgba(255,255,255,.08);
    color-scheme: dark;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 16px; line-height: 1.5;
    transition: background .25s, color .2s;
  }

  /* ── Header ───────────────────────────────────────────────────────────────── */
  .header {
    background: linear-gradient(135deg,#1c1c1c 0%,#111111 100%);
    border-bottom: 1px solid var(--border);
    padding: 24px 32px 20px; display: flex; align-items: center;
    justify-content: space-between; gap: 16px; flex-wrap: wrap;
    transition: background .25s;
  }
  :root[data-theme="light"] .header { background: linear-gradient(135deg,#f2f2f2 0%,#e8e8e8 100%); }
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) .header { background: linear-gradient(135deg,#f2f2f2 0%,#e8e8e8 100%); }
  }
  .header-left h1 { font-size: 24px; font-weight: 700; background: linear-gradient(90deg,#fdba74,#f97316); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
  .header-left p { color: var(--muted); font-size: 14px; margin-top: 2px; }
  .header-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .badge { display: inline-flex; align-items: center; gap: 6px; background: var(--surface2); border: 1px solid var(--border); border-radius: 20px; padding: 5px 12px; font-size: 13px; color: var(--muted); }
  .badge .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); }

  /* ── Theme toggle button ──────────────────────────────────────────────────── */
  .theme-btn {
    display: inline-flex; align-items: center; gap: 7px;
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 20px; padding: 6px 14px; cursor: pointer;
    font-size: 13px; color: var(--muted); font-family: inherit;
    transition: color .2s, border-color .2s, background .25s;
    white-space: nowrap;
  }
  .theme-btn:hover { color: var(--text); border-color: var(--accent); }
  .theme-btn svg { flex-shrink: 0; vertical-align: middle; }

  /* ── Tabs ─────────────────────────────────────────────────────────────────── */
  .tabs-wrap { padding: 16px 32px 0; display: flex; gap: 4px; flex-wrap: wrap; }
  .tab {
    background: transparent; border: 1px solid var(--border); color: var(--muted);
    border-radius: 8px 8px 0 0; padding: 9px 24px; cursor: pointer;
    font-size: 15px; font-weight: 500; transition: all .2s; font-family: inherit;
  }
  .tab:hover { color: var(--text); background: var(--surface); }
  .tab.active { background: var(--surface); border-bottom-color: var(--surface); color: var(--text); font-weight: 600; }

  /* ── Main panel ───────────────────────────────────────────────────────────── */
  .main { padding: 0 32px 40px; background: var(--surface); border: 1px solid var(--border); border-radius: 0 var(--radius) var(--radius) var(--radius); margin: 0 32px; }
  .section { padding: 24px 0; border-bottom: 1px solid var(--border); }
  .section:last-child { border-bottom: none; }
  .section-title { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .8px; color: var(--muted); margin-bottom: 16px; }

  /* ── KPI cards ────────────────────────────────────────────────────────────── */
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
  .kpi { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; position: relative; overflow: hidden; }
  .kpi::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--kpi-color, var(--accent)); }
  .kpi-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .6px; }
  .kpi-value { font-size: 36px; font-weight: 700; margin: 6px 0 2px; color: var(--text); line-height: 1; }
  .kpi-sub { font-size: 12px; color: var(--muted); }

  /* ── Chart cards ──────────────────────────────────────────────────────────── */
  .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; min-width: 0; }
  .chart-grid > * { min-width: 0; }
  @media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
  .chart-card { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; min-width: 0; }
  .chart-card h3 { font-size: 15px; font-weight: 600; margin-bottom: 14px; }
  .chart-card .sub { font-size: 12px; color: var(--muted); margin-top: -10px; margin-bottom: 14px; }
  .chart-wrap { position: relative; min-width: 0; overflow: hidden; }

  /* ── Insights banner ──────────────────────────────────────────────────────── */
  .top-req-banner { background: linear-gradient(135deg,rgba(249,115,22,.12),rgba(234,88,12,.07)); border: 1px solid rgba(249,115,22,.35); border-radius: var(--radius); padding: 20px 24px; display: flex; align-items: center; gap: 20px; }
  .top-req-icon { font-size: 38px; }
  .top-req-info h2 { font-size: 19px; font-weight: 700; color: #fb923c; }
  .top-req-info p { font-size: 13px; color: var(--muted); margin-top: 4px; }
  .insights-meta { margin-top: 10px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .insights-warn { font-size: 12px; color: #f97316; background: rgba(249,115,22,.1); border: 1px solid rgba(249,115,22,.35); border-radius: 20px; padding: 3px 10px; }
  .insights-updated { font-size: 12px; color: var(--muted); }

  /* ── Category bars ────────────────────────────────────────────────────────── */
  .cat-list { display: flex; flex-direction: column; gap: 10px; margin-top: 4px; }
  .cat-row { display: flex; align-items: center; gap: 12px; }
  .cat-row .label { width: 170px; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-shrink: 0; }
  .cat-row .bar-wrap { flex: 1; background: var(--bg); border-radius: 4px; height: 15px; overflow: hidden; display: flex; }
  .cat-bar { height: 100%; opacity: .85; }
  .cat-row .count { font-size: 12px; color: var(--muted); width: 30px; text-align: right; flex-shrink: 0; }

  /* ── Legend ───────────────────────────────────────────────────────────────── */
  .legend { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 12px; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); }
  .legend-dot { width: 11px; height: 11px; border-radius: 2px; flex-shrink: 0; }

  /* ── Tables ───────────────────────────────────────────────────────────────── */
  .q-table { width: 100%; border-collapse: collapse; font-size: 15px; }
  .q-table th { text-align: left; padding: 10px 14px; color: var(--muted); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .6px; border-bottom: 1px solid var(--border); }
  .q-table td { padding: 11px 14px; border-bottom: 1px solid var(--card-sep); }
  .q-table tr:last-child td { border-bottom: none; }
  .trend-up { color: var(--green); font-size: 12px; }
  .trend-dn { color: var(--red); font-size: 12px; }

  .q-panel { display: none; }
  .q-panel.active { display: block; }
  .footer { text-align: center; padding: 24px; color: var(--muted); font-size: 12px; }

  /* ── Chart height utility classes ─────────────────────────────────────────── */
  .chart-h-sm  { height: 220px; }
  .chart-h-md  { height: 260px; }
  .chart-h-lg  { height: 310px; }

  /* ── Overflow wrapper for wide tables ─────────────────────────────────────── */
  .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .table-wrap .q-table { min-width: 480px; }

  /* ── Responsive: tablet (≤ 900px) ─────────────────────────────────────────── */
  @media (max-width: 900px) {
    .chart-grid { grid-template-columns: 1fr; }
    .chart-h-lg { height: 260px; }
  }

  /* ── Responsive: mobile (≤ 640px) ─────────────────────────────────────────── */
  @media (max-width: 640px) {
    body { font-size: 15px; }

    .header { padding: 14px 16px 12px; gap: 10px; }
    .header-left h1 { font-size: 19px; }
    .header-left p  { font-size: 12px; }
    .badge      { font-size: 11px; padding: 4px 9px; }
    .theme-btn  { font-size: 11px; padding: 4px 9px; }

    .tabs-wrap {
      padding: 10px 16px 0;
      overflow-x: auto;
      flex-wrap: nowrap;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
    }
    .tabs-wrap::-webkit-scrollbar { display: none; }
    .tab { padding: 8px 16px; font-size: 13px; white-space: nowrap; flex-shrink: 0; }

    .main { margin: 0 10px; padding: 0 14px 28px; }
    .section { padding: 16px 0; }
    .section-title { font-size: 11px; }

    .kpi-grid { grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 8px; }
    .kpi { padding: 13px 14px; }
    .kpi-value { font-size: 28px; }
    .kpi-sub   { font-size: 11px; }

    .chart-h-sm { height: 190px; }
    .chart-h-md { height: 210px; }
    .chart-h-lg { height: 240px; }

    .chart-card { padding: 14px; }
    .chart-card h3 { font-size: 13px; margin-bottom: 10px; }
    .chart-card .sub { font-size: 11px; }

    .cat-row .label { width: 110px; font-size: 12px; }
    .legend { gap: 10px; }
    .legend-item { font-size: 12px; }

    .top-req-banner { flex-direction: column; gap: 12px; padding: 14px 16px; }
    .top-req-icon   { font-size: 28px; }
    .top-req-info h2 { font-size: 15px; }
    .top-req-info p  { font-size: 12px; }

    .q-table { font-size: 13px; }
    .q-table th, .q-table td { padding: 8px 10px; }
  }

  /* ── Responsive: small phone (≤ 400px) ────────────────────────────────────── */
  @media (max-width: 400px) {
    .header-right { gap: 4px; }
    .badge { display: none; }
    .kpi-grid { grid-template-columns: 1fr 1fr; }
    .cat-row .label { width: 90px; font-size: 11px; }
  }
"""


def generate_html(m: dict, insights: dict, csv_name: str, gen_date: str) -> str:
    q_order    = m['q_order']
    q_count    = m['total']
    ins_overall = insights.get('overall', {})
    ins_note    = ins_overall.get('description', 'No analysis available.')
    ins_title   = ins_overall.get('title', 'See insights.json')
    ins_icon    = ins_overall.get('icon', '📊')
    ins_updated = ins_overall.get('last_updated', 'N/A')
    ins_by      = ins_overall.get('updated_by', 'N/A')

    # Build per-quarter panels
    q_panels = '\n'.join(_gen_q_panel(q, m) for q in q_order)

    # Build tab buttons
    tab_buttons = '<button class="tab active" onclick="showTab(\'all\',this)">All Quarters</button>\n'
    for q in q_order:
        qd = m['quarters'][q]
        label = f'{q} ({qd["months"][0]}–{qd["months"][2]})'
        tab_buttons += f'<button class="tab" onclick="showTab(\'{q}\',this)">{label}</button>\n'

    # Legend for category bars
    legend_items = ''.join(
        f'<div class="legend-item"><div class="legend-dot" style="background:{_q_color(m["quarters"][q]["q_num"])}"></div>{q}</div>'
        for q in q_order
    )

    # Date range string
    years = sorted(set(m['quarters'][q]['year'] for q in q_order))
    yr_str = ' / '.join(str(y) for y in years)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DFR Tickets Dashboard — {yr_str} YTD</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>{CSS}</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>DFR Tickets — {yr_str} YTD Dashboard</h1>
    <p>Data Field Requests · {q_order[0] if q_order else ''} – {q_order[-1] if q_order else ''} · {q_count} tickets analysed</p>
  </div>
  <div class="header-right">
    <button id="theme-toggle" class="theme-btn" onclick="toggleTheme()" title="Toggle theme"></button>
    <div class="badge"><span class="dot"></span>Generated {gen_date}</div>
    <div class="badge">{csv_name}</div>
  </div>
</div>

<div class="tabs-wrap">
  {tab_buttons}
</div>

<div class="main">

  <!-- ── ALL QUARTERS PANEL ── -->
  <div id="panel-all" class="q-panel active">

    <div class="section">
      <div class="section-title">Overall Summary</div>
      {_gen_overall_kpis(m)}
    </div>

    <div class="section">
      <div class="section-title">Most Common Request Type
        <span class="insights-warn" style="margin-left:8px;font-style:normal">⚠ Requires AI to update</span>
      </div>
      <div class="top-req-banner">
        <div class="top-req-icon">{ins_icon}</div>
        <div class="top-req-info">
          <h2>{ins_title}</h2>
          <p>{ins_note}</p>
          <div class="insights-meta">
            <span class="insights-warn">⚠ This section is manually maintained — edit insights.json and re-run the script</span>
            <span class="insights-updated">Last updated: {ins_updated} by {ins_by}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Volume &amp; Request Types</div>
      <div class="chart-grid">
        <div class="chart-card">
          <h3>Monthly Ticket Volume</h3>
          <p class="sub">Colour = quarter</p>
          <div class="chart-wrap chart-h-md"><canvas id="monthly-chart"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Request Type Distribution</h3>
          <p class="sub">Inferred from Summary &amp; Description</p>
          <div class="chart-wrap chart-h-md"><canvas id="donut-chart"></canvas></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Request Categories — Quarter Comparison</div>
      <div class="legend">{legend_items}</div>
      <div class="cat-list" id="cat-bars"></div>
    </div>

    <div class="section">
      <div class="section-title">Team Activity</div>
      <div class="chart-grid">
        <div class="chart-card">
          <h3>Tickets by Assignee</h3>
          <p class="sub">Top 10</p>
          <div class="chart-wrap chart-h-lg"><canvas id="assignee-chart"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Avg Resolution Time by Assignee</h3>
          <p class="sub">Days from Created → Updated (≥2 tickets)</p>
          <div class="chart-wrap chart-h-lg"><canvas id="assignee-time-chart"></canvas></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Requests by Reporter</div>
      <div class="chart-card">
        <h3>Top 12 Reporters</h3>
        <div class="chart-wrap chart-h-lg"><canvas id="reporter-chart"></canvas></div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Priority &amp; Resolution Time</div>
      <div class="chart-grid">
        <div class="chart-card">
          <h3>Tickets by Priority</h3>
          <div class="chart-wrap chart-h-md"><canvas id="priority-chart"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Resolution Time Distribution</h3>
          <p class="sub">Created → Last Updated</p>
          <div class="chart-wrap chart-h-md"><canvas id="resolution-chart"></canvas></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Quarter-over-Quarter Comparison</div>
      <div class="chart-card">
        {_gen_comparison_table(m)}
      </div>
    </div>

  </div>

  <!-- ── PER-QUARTER PANELS ── -->
  {q_panels}

</div>

<div class="footer">DFR Tickets Analytics · {csv_name} · {q_count} tickets · Generated {gen_date}</div>

<script>
{_gen_js_data(m)}

// ── Palette ───────────────────────────────────────────────────────────────────
const PALETTE = {_j(PALETTE)};

// ── Theme helpers ─────────────────────────────────────────────────────────────
function isDark() {{
  const e = document.documentElement.getAttribute('data-theme');
  if (e === 'dark')  return true;
  if (e === 'light') return false;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}}

function tc() {{
  return isDark()
    ? {{ grid: 'rgba(255,255,255,.07)', text: '#c0c0c0', sliceBorder: '#272727'  }}
    : {{ grid: 'rgba(0,0,0,.12)',       text: '#555555', sliceBorder: '#e8e8e8'  }};
}}

// ── Chart registry ────────────────────────────────────────────────────────────
const charts = {{}};

function initCharts() {{
  // Destroy previous instances before re-rendering
  Object.values(charts).forEach(c => {{ try {{ c.destroy(); }} catch (_) {{}} }});

  const t = tc();
  Chart.defaults.color       = t.text;
  Chart.defaults.borderColor = t.grid;
  Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
  Chart.defaults.font.size   = 13;

  // Reusable scale configs
  const scX  = {{ grid: {{ display: false }},  ticks: {{ color: t.text }} }};
  const scY  = {{ grid: {{ color: t.grid }},   ticks: {{ color: t.text }}, beginAtZero: true }};
  const scYH = {{ grid: {{ display: false }},  ticks: {{ color: t.text, font: {{ size: 13 }} }} }};
  const scXH = {{ grid: {{ color: t.grid }},   ticks: {{ color: t.text }}, beginAtZero: true }};
  const noLeg = {{ legend: {{ display: false }} }};

  // ── Monthly bar ─────────────────────────────────────────────────────────────
  charts.monthly = new Chart(document.getElementById('monthly-chart'), {{
    type: 'bar',
    data: {{
      labels: M.months,
      datasets: [{{ label: 'Tickets', data: M.monthlyValues,
        backgroundColor: M.monthlyQs.map(q => M.qColors[q] + 'cc'),
        borderColor:     M.monthlyQs.map(q => M.qColors[q]),
        borderWidth: 1.5, borderRadius: 5, borderSkipped: false }}]
    }},
    options: {{ responsive: true, maintainAspectRatio: false,
      plugins: noLeg, scales: {{ x: scX, y: scY }}
    }}
  }});

  // ── Overall donut ───────────────────────────────────────────────────────────
  charts.donut = new Chart(document.getElementById('donut-chart'), {{
    type: 'doughnut',
    data: {{ labels: M.catLabels, datasets: [{{ data: M.catValues,
      backgroundColor: PALETTE, borderColor: t.sliceBorder, borderWidth: 2, hoverOffset: 8 }}] }},
    options: {{ responsive: true, maintainAspectRatio: false, cutout: '58%',
      plugins: {{
        legend: {{ position: 'right', labels: {{ boxWidth: 12, padding: 10, color: t.text, font: {{ size: 13 }} }} }},
        tooltip: {{ callbacks: {{ label: c => ` ${{c.label}}: ${{c.raw}} (${{(c.raw/M.total*100).toFixed(1)}}%)` }} }}
      }}
    }}
  }});

  // ── Category stacked bars (DOM, not Chart.js) ───────────────────────────────
  const container = document.getElementById('cat-bars');
  container.innerHTML = '';
  const maxTotal = Math.max(...catData.totals);
  catData.labels.forEach((label, i) => {{
    const total = catData.totals[i];
    if (total === 0) return;
    const row = document.createElement('div');
    row.className = 'cat-row';
    let barHtml = '';
    M.qOrder.forEach(q => {{
      const v = (catData.quarters[q] || [])[i] || 0;
      const pct = (v / maxTotal * 100).toFixed(1);
      barHtml += `<div class="cat-bar" style="width:${{pct}}%;background:${{catData.q_colors[q]}}"></div>`;
    }});
    row.innerHTML = `<span class="label" title="${{label}}">${{label}}</span>
      <div class="bar-wrap">${{barHtml}}</div>
      <span class="count">${{total}}</span>`;
    container.appendChild(row);
  }});

  // ── Assignee count ──────────────────────────────────────────────────────────
  charts.asgn = new Chart(document.getElementById('assignee-chart'), {{
    type: 'bar',
    data: {{ labels: M.asgnLabels, datasets: [{{ label: 'Tickets', data: M.asgnCounts,
      backgroundColor: M.asgnCounts.map(v => `rgba(249,115,22,${{(0.35+v/Math.max(...M.asgnCounts)*0.65).toFixed(2)}})` ),
      borderColor: '#f97316', borderWidth: 1, borderRadius: 4 }}] }},
    options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: noLeg, scales: {{ x: scXH, y: scYH }}
    }}
  }});

  // ── Assignee avg resolution time ────────────────────────────────────────────
  charts.asgnTime = new Chart(document.getElementById('assignee-time-chart'), {{
    type: 'bar',
    data: {{ labels: M.asgnLabels, datasets: [{{ label: 'Avg Days', data: M.asgnAvgDays,
      backgroundColor: M.asgnAvgDays.map(v => v>20?'#ef444499':v>7?'#f9731699':'#22c55e99'),
      borderColor:     M.asgnAvgDays.map(v => v>20?'#ef4444':v>7?'#f97316':'#22c55e'),
      borderWidth: 1, borderRadius: 4 }}] }},
    options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: {{ ...noLeg, tooltip: {{ callbacks: {{ label: t => ` ${{t.raw}} days avg` }} }} }},
      scales: {{ x: scXH, y: scYH }}
    }}
  }});

  // ── Reporter bar ────────────────────────────────────────────────────────────
  charts.reporter = new Chart(document.getElementById('reporter-chart'), {{
    type: 'bar',
    data: {{ labels: M.repLabels, datasets: [{{ label: 'Tickets Submitted', data: M.repValues,
      backgroundColor: PALETTE.map(c => c+'bb'), borderColor: PALETTE, borderWidth: 1, borderRadius: 4 }}] }},
    options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: noLeg, scales: {{ x: scXH, y: scYH }}
    }}
  }});

  // ── Priority donut ──────────────────────────────────────────────────────────
  charts.priority = new Chart(document.getElementById('priority-chart'), {{
    type: 'doughnut',
    data: {{ labels: M.prioLabels, datasets: [{{ data: M.prioValues,
      backgroundColor: ['#ef4444','#f97316','#f59e0b','#22c55e','#9ca3af'],
      borderColor: t.sliceBorder, borderWidth: 2, hoverOffset: 6 }}] }},
    options: {{ responsive: true, maintainAspectRatio: false, cutout: '55%',
      plugins: {{
        legend: {{ position: 'right', labels: {{ boxWidth: 12, padding: 10, color: t.text, font: {{ size: 13 }} }} }},
        tooltip: {{ callbacks: {{ label: tt => ` ${{tt.label}}: ${{tt.raw}} (${{(tt.raw/M.total*100).toFixed(1)}}%)` }} }}
      }}
    }}
  }});

  // ── Resolution time distribution ────────────────────────────────────────────
  charts.resolution = new Chart(document.getElementById('resolution-chart'), {{
    type: 'bar',
    data: {{ labels: M.bucketLabels, datasets: [{{ label: 'Tickets', data: M.bucketValues,
      backgroundColor: ['#22c55ecc','#22c55e88','#f97316cc','#f59e0b99','#ef444499','#ef4444cc'],
      borderColor:     ['#22c55e','#22c55e','#f97316','#f59e0b','#ef4444','#ef4444'],
      borderWidth: 1.5, borderRadius: 5 }}] }},
    options: {{ responsive: true, maintainAspectRatio: false,
      plugins: noLeg, scales: {{ x: scX, y: scY }}
    }}
  }});

  // ── Per-quarter charts ──────────────────────────────────────────────────────
  M.qOrder.forEach(q => {{
    const qd = M.qChartData[q];
    if (!qd) return;

    const mCanvas = document.getElementById(q + '-monthly');
    if (mCanvas) {{
      charts['q' + q + 'monthly'] = new Chart(mCanvas, {{
        type: 'bar',
        data: {{ labels: qd.monthly_labels, datasets: [{{ label: 'Tickets', data: qd.monthly_counts,
          backgroundColor: qd.color + 'bb', borderColor: qd.color, borderWidth: 1.5, borderRadius: 6 }}] }},
        options: {{ responsive: true, maintainAspectRatio: false,
          plugins: noLeg, scales: {{ x: scX, y: scY }}
        }}
      }});
    }}

    const cCanvas = document.getElementById(q + '-cats');
    if (cCanvas) {{
      charts['q' + q + 'cats'] = new Chart(cCanvas, {{
        type: 'doughnut',
        data: {{ labels: qd.cat_labels, datasets: [{{ data: qd.cat_values,
          backgroundColor: PALETTE, borderColor: t.sliceBorder, borderWidth: 2, hoverOffset: 6 }}] }},
        options: {{ responsive: true, maintainAspectRatio: false, cutout: '55%',
          plugins: {{
            legend: {{ position: 'right', labels: {{ boxWidth: 11, padding: 8, color: t.text, font: {{ size: 12 }} }} }},
            tooltip: {{ callbacks: {{ label: tt => ` ${{tt.label}}: ${{tt.raw}}` }} }}
          }}
        }}
      }});
    }}
  }});
}}

// ── Theme toggle ──────────────────────────────────────────────────────────────
const SUN_SVG  = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.5"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
const MOON_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';

function updateThemeBtn() {{
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const dark = isDark();
  btn.innerHTML = dark ? SUN_SVG + ' Light' : MOON_SVG + '  Dark';
  btn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
}}

function toggleTheme() {{
  const next = !isDark();
  document.documentElement.setAttribute('data-theme', next ? 'dark' : 'light');
  localStorage.setItem('dfr-theme', next ? 'dark' : 'light');
  updateThemeBtn();
  initCharts();
}}

// ── Tab switching ─────────────────────────────────────────────────────────────
function showTab(name, el) {{
  document.querySelectorAll('.q-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  el.classList.add('active');
}}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
(function () {{
  const saved = localStorage.getItem('dfr-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  updateThemeBtn();
  initCharts();

  const resizeAll = () => {{
    Object.values(charts).forEach(c => {{ try {{ c.resize(); }} catch (_) {{}} }});
  }};
  // Observe the main container — one observer catches all grid reflows including 2-col layouts.
  // Double rAF lets the CSS layout fully settle before Chart.js reads new dimensions.
  if (typeof ResizeObserver !== 'undefined') {{
    const ro = new ResizeObserver(() => requestAnimationFrame(() => requestAnimationFrame(resizeAll)));
    const mainEl = document.querySelector('.main');
    if (mainEl) ro.observe(mainEl);
  }}
  // Also run debounced window resize in parallel (not a fallback)
  let _rt;
  window.addEventListener('resize', () => {{
    clearTimeout(_rt);
    _rt = setTimeout(resizeAll, 150);
  }});
}})();
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Regenerate DFR Dashboard HTML from CSV.')
    parser.add_argument('--csv', default=str(DEFAULT_CSV), help='Path to CSV export')
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='Output HTML path')
    args = parser.parse_args()

    csv_path = Path(args.csv)
    out_path = Path(args.out)

    if not csv_path.exists():
        print(f'ERROR: CSV not found: {csv_path}', file=sys.stderr)
        sys.exit(1)

    print(f'Loading  {csv_path.name} …')
    rows = load_rows(csv_path)
    print(f'  {len(rows)} rows loaded')

    print('Computing metrics …')
    metrics = compute(rows)
    print(f'  Quarters detected: {", ".join(metrics["q_order"])}')
    print(f'  Total tickets: {metrics["total"]}')

    # Load insights
    insights = {}
    if INSIGHTS_FILE.exists():
        with open(INSIGHTS_FILE, 'r', encoding='utf-8') as f:
            insights = json.load(f)
        print(f'  Insights loaded from {INSIGHTS_FILE.name}')
    else:
        print(f'  WARNING: {INSIGHTS_FILE.name} not found — insights section will be empty.')

    gen_date = datetime.now().strftime('%Y-%m-%d')
    print(f'Generating HTML …')
    html = generate_html(metrics, insights, csv_path.name, gen_date)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    size_kb = out_path.stat().st_size // 1024
    print(f'  Written: {out_path} ({size_kb} KB)')
    print(f'\nDone. Open {out_path.name} in a browser, or run server.py to serve it.')


if __name__ == '__main__':
    main()
