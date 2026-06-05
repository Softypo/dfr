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

PALETTE       = ['#4f6ef7','#f76b4f','#29c48a','#f7c84f','#a78bfa','#34d399',
                 '#fb923c','#60a5fa','#f472b6','#a3e635','#38bdf8','#e879f9','#4ade80']
Q_HUE_COLORS  = ['#4f6ef7','#f76b4f','#29c48a','#f7c84f','#a78bfa','#38bdf8',
                 '#fb923c','#f472b6']

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
        {_gen_kpi("Total Tickets", str(m["total"]), "YTD total", "#4f6ef7")}
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
      <table class="q-table">
        <thead><tr>{header_cells}</tr></thead>
        <tbody>
          {row("Total Tickets", counts, cnt_trend)}
          {row("Avg Resolution", avgs, speed_html)}
          {row("Top Request Type", tops)}
          {row("Peak Month", peaks)}
          {row("Completion Rate", comps)}
        </tbody>
      </table>'''


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
          <div class="chart-wrap" style="height:220px">
            <canvas id="{q}-monthly"></canvas>
          </div>
        </div>
        <div class="chart-card">
          <h3>Request Categories — {q}</h3>
          <div class="chart-wrap" style="height:220px">
            <canvas id="{q}-cats"></canvas>
          </div>
        </div>
      </div>
    </div>
    <div class="section">
      <div class="section-title">{q} Category Breakdown</div>
      <div class="chart-card">
        <table class="q-table">
          <thead><tr><th>Category</th><th>Count</th><th>% of {q}</th></tr></thead>
          <tbody>{_gen_cat_table_rows(qd)}</tbody>
        </table>
      </div>
    </div>
  </div>'''


# ── Full HTML assembly ────────────────────────────────────────────────────────

CSS = r"""
  :root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --border: #2d3149; --accent: #4f6ef7; --green: #29c48a;
    --yellow: #f7c84f; --red: #f74f4f; --text: #e2e8f0; --muted: #8892a4; --radius: 12px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; line-height: 1.5; }

  .header { background: linear-gradient(135deg,#1a1d27 0%,#141627 100%); border-bottom: 1px solid var(--border); padding: 24px 32px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .header-left h1 { font-size: 22px; font-weight: 700; background: linear-gradient(90deg,#a5b4fc,#7c5cfc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
  .header-left p { color: var(--muted); font-size: 12px; margin-top: 2px; }
  .header-right { display: flex; align-items: center; gap: 8px; }
  .badge { display: inline-flex; align-items: center; gap: 6px; background: var(--surface2); border: 1px solid var(--border); border-radius: 20px; padding: 5px 12px; font-size: 12px; color: var(--muted); }
  .badge .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); }

  .tabs-wrap { padding: 16px 32px 0; display: flex; gap: 4px; flex-wrap: wrap; }
  .tab { background: transparent; border: 1px solid var(--border); color: var(--muted); border-radius: 8px 8px 0 0; padding: 8px 22px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all .2s; }
  .tab:hover { color: var(--text); background: var(--surface); }
  .tab.active { background: var(--surface); border-bottom-color: var(--surface); color: var(--text); font-weight: 600; }

  .main { padding: 0 32px 40px; background: var(--surface); border: 1px solid var(--border); border-radius: 0 var(--radius) var(--radius) var(--radius); margin: 0 32px; }
  .section { padding: 24px 0; border-bottom: 1px solid var(--border); }
  .section:last-child { border-bottom: none; }
  .section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 16px; }

  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
  .kpi { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 18px; position: relative; overflow: hidden; }
  .kpi::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--kpi-color, var(--accent)); }
  .kpi-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .6px; }
  .kpi-value { font-size: 32px; font-weight: 700; margin: 6px 0 2px; color: var(--text); line-height: 1; }
  .kpi-sub { font-size: 11px; color: var(--muted); }

  .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
  .chart-card { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px; }
  .chart-card h3 { font-size: 13px; font-weight: 600; margin-bottom: 14px; }
  .chart-card .sub { font-size: 11px; color: var(--muted); margin-top: -10px; margin-bottom: 14px; }
  .chart-wrap { position: relative; }

  .top-req-banner { background: linear-gradient(135deg,rgba(79,110,247,.15),rgba(124,92,252,.1)); border: 1px solid rgba(79,110,247,.3); border-radius: var(--radius); padding: 18px 22px; display: flex; align-items: center; gap: 18px; }
  .top-req-icon { font-size: 36px; }
  .top-req-info h2 { font-size: 17px; font-weight: 700; color: #a5b4fc; }
  .top-req-info p { font-size: 12px; color: var(--muted); margin-top: 3px; }
  .insights-meta { margin-top: 10px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .insights-warn { font-size: 11px; color: #f7c84f; background: rgba(247,200,79,.1); border: 1px solid rgba(247,200,79,.3); border-radius: 20px; padding: 3px 10px; }
  .insights-updated { font-size: 11px; color: var(--muted); }

  .cat-list { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
  .cat-row { display: flex; align-items: center; gap: 10px; }
  .cat-row .label { width: 160px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-shrink: 0; }
  .cat-row .bar-wrap { flex: 1; background: var(--bg); border-radius: 4px; height: 14px; overflow: hidden; display: flex; }
  .cat-bar { height: 100%; opacity: .85; }
  .cat-row .count { font-size: 11px; color: var(--muted); width: 28px; text-align: right; flex-shrink: 0; }

  .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
  .legend-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }

  .q-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .q-table th { text-align: left; padding: 8px 12px; color: var(--muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .6px; border-bottom: 1px solid var(--border); }
  .q-table td { padding: 9px 12px; border-bottom: 1px solid rgba(45,49,73,.5); }
  .q-table tr:last-child td { border-bottom: none; }
  .trend-up { color: var(--green); font-size: 11px; }
  .trend-dn { color: var(--red); font-size: 11px; }

  .q-panel { display: none; }
  .q-panel.active { display: block; }
  .footer { text-align: center; padding: 24px; color: var(--muted); font-size: 11px; }
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
          <div class="chart-wrap" style="height:240px"><canvas id="monthly-chart"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Request Type Distribution</h3>
          <p class="sub">Inferred from Summary &amp; Description</p>
          <div class="chart-wrap" style="height:240px"><canvas id="donut-chart"></canvas></div>
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
          <div class="chart-wrap" style="height:280px"><canvas id="assignee-chart"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Avg Resolution Time by Assignee</h3>
          <p class="sub">Days from Created → Updated (≥2 tickets)</p>
          <div class="chart-wrap" style="height:280px"><canvas id="assignee-time-chart"></canvas></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Requests by Reporter</div>
      <div class="chart-card">
        <h3>Top 12 Reporters</h3>
        <div class="chart-wrap" style="height:280px"><canvas id="reporter-chart"></canvas></div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Priority &amp; Resolution Time</div>
      <div class="chart-grid">
        <div class="chart-card">
          <h3>Tickets by Priority</h3>
          <div class="chart-wrap" style="height:240px"><canvas id="priority-chart"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Resolution Time Distribution</h3>
          <p class="sub">Created → Last Updated</p>
          <div class="chart-wrap" style="height:240px"><canvas id="resolution-chart"></canvas></div>
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

// ── Chart.js defaults ────────────────────────────────────────────────────────
Chart.defaults.color = '#8892a4';
Chart.defaults.borderColor = '#2d3149';
Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
Chart.defaults.font.size = 12;

const PALETTE = {_j(PALETTE)};

// ── Monthly bar ──────────────────────────────────────────────────────────────
new Chart(document.getElementById('monthly-chart'), {{
  type: 'bar',
  data: {{
    labels: M.months,
    datasets: [{{ label: 'Tickets', data: M.monthlyValues,
      backgroundColor: M.monthlyQs.map(q => M.qColors[q] + 'cc'),
      borderColor:     M.monthlyQs.map(q => M.qColors[q]),
      borderWidth: 1.5, borderRadius: 5, borderSkipped: false }}]
  }},
  options: {{ responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ grid: {{ display: false }} }}, y: {{ grid: {{ color: '#2d314960' }}, beginAtZero: true }} }}
  }}
}});

// ── Overall donut ────────────────────────────────────────────────────────────
new Chart(document.getElementById('donut-chart'), {{
  type: 'doughnut',
  data: {{ labels: M.catLabels, datasets: [{{ data: M.catValues,
    backgroundColor: PALETTE, borderColor: '#1a1d27', borderWidth: 2, hoverOffset: 8 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, cutout: '58%',
    plugins: {{
      legend: {{ position: 'right', labels: {{ boxWidth: 11, padding: 8, font: {{ size: 11 }} }} }},
      tooltip: {{ callbacks: {{ label: c => ` ${{c.label}}: ${{c.raw}} (${{(c.raw/M.total*100).toFixed(1)}}%)` }} }}
    }}
  }}
}});

// ── Category stacked bars ────────────────────────────────────────────────────
(function() {{
  const container = document.getElementById('cat-bars');
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
}})();

// ── Assignee bar ─────────────────────────────────────────────────────────────
new Chart(document.getElementById('assignee-chart'), {{
  type: 'bar',
  data: {{ labels: M.asgnLabels, datasets: [{{ label: 'Tickets', data: M.asgnCounts,
    backgroundColor: M.asgnCounts.map(v => `rgba(79,110,247,${{(0.4+v/Math.max(...M.asgnCounts)*0.6).toFixed(2)}})` ),
    borderColor: '#4f6ef7', borderWidth: 1, borderRadius: 4 }}] }},
  options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ grid: {{ color: '#2d314960' }}, beginAtZero: true }}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }} }}
  }}
}});

// ── Assignee avg days ────────────────────────────────────────────────────────
new Chart(document.getElementById('assignee-time-chart'), {{
  type: 'bar',
  data: {{ labels: M.asgnLabels, datasets: [{{ label: 'Avg Days', data: M.asgnAvgDays,
    backgroundColor: M.asgnAvgDays.map(v => v>20?'#f74f4f99':v>7?'#f7c84f99':'#29c48a99'),
    borderColor:     M.asgnAvgDays.map(v => v>20?'#f74f4f':v>7?'#f7c84f':'#29c48a'),
    borderWidth: 1, borderRadius: 4 }}] }},
  options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: t => ` ${{t.raw}} days avg` }} }} }},
    scales: {{ x: {{ grid: {{ color: '#2d314960' }}, beginAtZero: true }}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }} }}
  }}
}});

// ── Reporter bar ─────────────────────────────────────────────────────────────
new Chart(document.getElementById('reporter-chart'), {{
  type: 'bar',
  data: {{ labels: M.repLabels, datasets: [{{ label: 'Tickets Submitted', data: M.repValues,
    backgroundColor: PALETTE.map(c => c+'bb'), borderColor: PALETTE, borderWidth: 1, borderRadius: 4 }}] }},
  options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ grid: {{ color: '#2d314960' }}, beginAtZero: true }}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }} }}
  }}
}});

// ── Priority donut ───────────────────────────────────────────────────────────
new Chart(document.getElementById('priority-chart'), {{
  type: 'doughnut',
  data: {{ labels: M.prioLabels, datasets: [{{ data: M.prioValues,
    backgroundColor: ['#f74f4f','#f7914f','#4f6ef7','#29c48a','#8892a4'],
    borderColor: '#1a1d27', borderWidth: 2, hoverOffset: 6 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, cutout: '55%',
    plugins: {{
      legend: {{ position: 'right', labels: {{ boxWidth: 11, padding: 10, font: {{ size: 11 }} }} }},
      tooltip: {{ callbacks: {{ label: t => ` ${{t.label}}: ${{t.raw}} (${{(t.raw/M.total*100).toFixed(1)}}%)` }} }}
    }}
  }}
}});

// ── Resolution distribution ──────────────────────────────────────────────────
new Chart(document.getElementById('resolution-chart'), {{
  type: 'bar',
  data: {{ labels: M.bucketLabels, datasets: [{{ label: 'Tickets', data: M.bucketValues,
    backgroundColor: ['#29c48acc','#29c48a88','#4f6ef7cc','#f7c84f99','#f7914f99','#f74f4f99'],
    borderColor:     ['#29c48a','#29c48a','#4f6ef7','#f7c84f','#f7914f','#f74f4f'],
    borderWidth: 1.5, borderRadius: 5 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ grid: {{ display: false }} }}, y: {{ grid: {{ color: '#2d314960' }}, beginAtZero: true }} }}
  }}
}});

// ── Per-quarter charts ───────────────────────────────────────────────────────
M.qOrder.forEach(q => {{
  const qd = M.qChartData[q];
  if (!qd) return;

  const mCanvas = document.getElementById(q + '-monthly');
  if (mCanvas) {{
    new Chart(mCanvas, {{
      type: 'bar',
      data: {{ labels: qd.monthly_labels, datasets: [{{ label: 'Tickets', data: qd.monthly_counts,
        backgroundColor: qd.color + 'bb', borderColor: qd.color, borderWidth: 1.5, borderRadius: 6 }}] }},
      options: {{ responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ grid: {{ display: false }} }}, y: {{ grid: {{ color: '#2d314960' }}, beginAtZero: true }} }}
      }}
    }});
  }}

  const cCanvas = document.getElementById(q + '-cats');
  if (cCanvas) {{
    new Chart(cCanvas, {{
      type: 'doughnut',
      data: {{ labels: qd.cat_labels, datasets: [{{ data: qd.cat_values,
        backgroundColor: PALETTE, borderColor: '#1a1d27', borderWidth: 2, hoverOffset: 6 }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, cutout: '55%',
        plugins: {{
          legend: {{ position: 'right', labels: {{ boxWidth: 10, padding: 7, font: {{ size: 10 }} }} }},
          tooltip: {{ callbacks: {{ label: t => ` ${{t.label}}: ${{t.raw}}` }} }}
        }}
      }}
    }});
  }}
}});

// ── Tab switching ────────────────────────────────────────────────────────────
function showTab(name, el) {{
  document.querySelectorAll('.q-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  el.classList.add('active');
}}
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
