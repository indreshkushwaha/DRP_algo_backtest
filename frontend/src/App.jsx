import { useState, useEffect, useRef } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
  Label,
} from 'recharts'
import './App.css'

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : 'https://drp-algo-backtest.onrender.com')

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function computeEntryDatetime(expiryDate, entryDay, entryTime) {
  const [y, m, d] = expiryDate.split('-').map(Number)
  const expiry = new Date(y, m - 1, d)
  const weekday = (expiry.getDay() + 6) % 7
  const monday = new Date(expiry)
  monday.setDate(expiry.getDate() - weekday)
  const entryDate = new Date(monday)
  entryDate.setDate(monday.getDate() + entryDay)
  const Y = entryDate.getFullYear()
  const M = String(entryDate.getMonth() + 1).padStart(2, '0')
  const D = String(entryDate.getDate()).padStart(2, '0')
  const timePart = entryTime.includes(':') ? entryTime : `${entryTime}:00`
  const [hh, mm] = timePart.split(':')
  return `${Y}-${M}-${D} ${hh}:${mm || '00'}:00`
}

function computeExitDatetime(expiryDate, exitDay, exitTime) {
  const [y, m, d] = expiryDate.split('-').map(Number)
  const expiry = new Date(y, m - 1, d)
  const weekday = (expiry.getDay() + 6) % 7
  const monday = new Date(expiry)
  monday.setDate(expiry.getDate() - weekday)
  const exitDate = new Date(monday)
  exitDate.setDate(monday.getDate() + exitDay)
  const Y = exitDate.getFullYear()
  const M = String(exitDate.getMonth() + 1).padStart(2, '0')
  const D = String(exitDate.getDate()).padStart(2, '0')
  const timePart = exitTime.includes(':') ? exitTime : `${exitTime}:00`
  const [hh, mm] = timePart.split(':')
  return `${Y}-${M}-${D} ${hh}:${mm || '00'}:00`
}

function formatDateTime(str) {
  if (str == null || str === '') return ''
  const s = String(str).trim()
  if (!s) return ''
  const withoutT = s.replace('T', ' ')
  const dot = withoutT.indexOf('.')
  return dot >= 0 ? withoutT.slice(0, dot) : withoutT
}

function defaultExpiryFromDate() {
  const d = new Date()
  d.setMonth(d.getMonth() - 6)
  return d.toISOString().slice(0, 10)
}

function defaultExpiryToDate() {
  return new Date().toISOString().slice(0, 10)
}

const defaultConfig = {
  entry_day: 0,
  entry_time: '13:15',
  exit_day: 2,
  exit_time: '14:10',
  target_premium: 50,
  expiry_date: '2025-07-29',
  underlying_key: 'BSE_INDEX|SENSEX',
  option_type: 'CE',
  strike_gap: 100,
  tolerance: 5,
  hedge_difference: 300,
  square_off_when_short_below: 145,
  short_pair: true,
  phase2_trigger_premium: 68,
  phase2_target_reentry: 50,
  phase2_strike_range: 15,
  phase2b_trigger_premium: 75,
  phase2b_target_reentry: 50,
  phase2c_trigger_premium: 88,
  phase2c_target_reentry: 50,
  phase3_trigger_premium: 98,
  phase3_target_reentry: 50,
  phase4_trigger_premium: 115,
  phase4_target_reentry: 50,
  stoploss_amount: 5000,
  margin: '',
  profit_pct: '',
  lot_size: 1,
}

const STORAGE_KEY = 'upstox_backtest_saved_runs'

function loadSavedRuns() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function App() {
  const [token, setToken] = useState('')
  const [tokenSaved, setTokenSaved] = useState(false)
  const [config, setConfig] = useState(defaultConfig)
  const [data, setData] = useState([])
  const [columns, setColumns] = useState([])
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [expiryFromDate, setExpiryFromDate] = useState(defaultExpiryFromDate)
  const [expiryToDate, setExpiryToDate] = useState(defaultExpiryToDate)
  const [expiries, setExpiries] = useState([])
  const [expiriesLoading, setExpiriesLoading] = useState(false)
  const [expiriesError, setExpiriesError] = useState('')
  const [expiriesMessage, setExpiriesMessage] = useState('')
  const [savedRuns, setSavedRuns] = useState([])
  const [selectedExpiriesForCombine, setSelectedExpiriesForCombine] = useState([])
  const [showGraph, setShowGraph] = useState(true)
  const [showTokenForm, setShowTokenForm] = useState(false)
  const tokenSavedTimeoutRef = useRef(null)

  useEffect(() => {
    setSavedRuns(loadSavedRuns())
  }, [])

  useEffect(() => {
    return () => {
      if (tokenSavedTimeoutRef.current) clearTimeout(tokenSavedTimeoutRef.current)
    }
  }, [])

  useEffect(() => {
    fetch(`${API_BASE}/api/config/defaults`)
      .then((r) => r.json())
      .then((d) => setConfig((c) => ({ ...c, ...d })))
      .catch(() => {})
    fetch(`${API_BASE}/api/config/token`)
      .then((r) => r.json())
      .then((d) => setToken(d.access_token || ''))
      .catch(() => {})
  }, [])

  const fetchExpiries = () => {
    const key = config.underlying_key
    if (!key || !expiryFromDate || !expiryToDate) {
      setExpiries([])
      setExpiriesError('')
      setExpiriesMessage('')
      return
    }
    setExpiriesLoading(true)
    setExpiriesError('')
    setExpiriesMessage('')
    const params = new URLSearchParams({
      instrument_key: key,
      from_date: expiryFromDate,
      to_date: expiryToDate,
    })
    fetch(`${API_BASE}/api/expiries?${params}`)
      .then((r) => r.json())
      .then((res) => {
        const list = res.expiries || []
        setExpiries(list)
        setExpiriesError(res.error || '')
        setExpiriesMessage(res.range_matched === false ? (res.message || '') : '')
        setConfig((c) => {
          if (list.length && (!c.expiry_date || !list.includes(c.expiry_date))) {
            return { ...c, expiry_date: list[0] }
          }
          return c
        })
      })
      .catch((e) => {
        setExpiries([])
        setExpiriesError(e.message || 'Failed to fetch expiries')
        setExpiriesMessage('')
      })
      .finally(() => setExpiriesLoading(false))
  }

  useEffect(() => {
    fetchExpiries()
  }, [config.underlying_key, expiryFromDate, expiryToDate])

  const saveToken = () => {
    setError('')
    setTokenSaved(false)
    setLoading(true)
    if (tokenSavedTimeoutRef.current) {
      clearTimeout(tokenSavedTimeoutRef.current)
      tokenSavedTimeoutRef.current = null
    }
    fetch(`${API_BASE}/api/config/token`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: token }),
    })
      .then((r) => {
        if (!r.ok) throw new Error('Failed to save token')
        setShowTokenForm(false)
        setTokenSaved(true)
        tokenSavedTimeoutRef.current = setTimeout(() => {
          setTokenSaved(false)
          tokenSavedTimeoutRef.current = null
        }, 2500)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  const runBacktest = () => {
    setError('')
    const lotNum = config.lot_size === '' ? null : Number(config.lot_size)
    if (lotNum != null && (Number.isNaN(lotNum) || lotNum < 1)) {
      setError('Lot size cannot be less than 1')
      return
    }
    setData([])
    setColumns([])
    setSummary(null)
    setShowGraph(false)
    setBacktestLoading(true)
    const body = {
      ...config,
      entry_datetime: computeEntryDatetime(
        config.expiry_date,
        config.entry_day ?? 0,
        config.entry_time ?? '13:15',
      ),
      exit_datetime: computeExitDatetime(
        config.expiry_date,
        config.exit_day ?? 2,
        config.exit_time ?? '14:10',
      ),
      hedge_difference: config.hedge_difference === '' ? null : Number(config.hedge_difference),
      square_off_when_short_below: config.square_off_when_short_below === '' ? null : Number(config.square_off_when_short_below),
      phase2_trigger_premium: config.phase2_trigger_premium === '' ? null : Number(config.phase2_trigger_premium),
      phase2b_trigger_premium: config.phase2b_trigger_premium === '' ? null : Number(config.phase2b_trigger_premium),
      phase2c_trigger_premium: config.phase2c_trigger_premium === '' ? null : Number(config.phase2c_trigger_premium),
      phase3_trigger_premium: config.phase3_trigger_premium === '' ? null : Number(config.phase3_trigger_premium),
      phase4_trigger_premium: config.phase4_trigger_premium === '' ? null : Number(config.phase4_trigger_premium),
      stoploss_amount: config.stoploss_amount === '' ? null : Number(config.stoploss_amount),
      margin: config.margin === '' ? null : Number(config.margin),
      profit_pct: config.profit_pct === '' ? null : Number(config.profit_pct),
      lot_size: config.lot_size === '' ? null : Number(config.lot_size),
    }
    fetch(`${API_BASE}/api/backtest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((r) => {
        if (!r.ok) return r.json().then((e) => {
          const msg = typeof e.detail === 'string' ? e.detail : Array.isArray(e.detail) ? e.detail.map((x) => x.msg || JSON.stringify(x)).join(', ') : 'Backtest failed'
          throw new Error(msg)
        })
        return r.json()
      })
      .then((res) => {
        setData(res.data || [])
        setColumns(res.columns || [])
        setSummary(res.summary || null)
      })
      .catch((e) => setError(e.message || 'Backtest failed'))
      .finally(() => setBacktestLoading(false))
  }

  const updateConfig = (key, value) => {
    if (key === 'lot_size' && value !== '') {
      const num = Number(value)
      if (!Number.isNaN(num) && num < 1) value = 1
    }
    setConfig((c) => ({ ...c, [key]: value }))
  }

  const saveRun = () => {
    if (!summary || data.length === 0) return
    const run = {
      underlying_key: config.underlying_key,
      expiry_date: config.expiry_date,
      summary: { ...summary },
      data: [...data],
      columns: [...columns],
      savedAt: new Date().toISOString(),
    }
    const current = loadSavedRuns()
    const rest = current.filter(
      (r) => !(r.underlying_key === run.underlying_key && r.expiry_date === run.expiry_date)
    )
    const next = [...rest, run]
    setSavedRuns(next)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  }

  const runsForUnderlying = savedRuns.filter((r) => r.underlying_key === config.underlying_key)
  const selectedRuns = runsForUnderlying.filter((r) => selectedExpiriesForCombine.includes(r.expiry_date))
  const combinedSummary =
    selectedRuns.length > 0
      ? (() => {
          const sumFinalPnl = selectedRuns.reduce((a, r) => a + Number(r.summary.final_pnl || 0), 0)
          const sumBars = selectedRuns.reduce((a, r) => a + Number(r.summary.num_bars || 0), 0)
          const minDrawdownRun = selectedRuns.reduce((best, r) =>
            Number(r.summary.max_drawdown_amount ?? 0) < Number(best.summary.max_drawdown_amount ?? 0) ? r : best
          )
          const maxProfitRun = selectedRuns.reduce((best, r) =>
            Number(r.summary.max_profit_amount ?? 0) > Number(best.summary.max_profit_amount ?? 0) ? r : best
          )
          const starts = selectedRuns.map((r) => r.summary.start_datetime || '')
          const ends = selectedRuns.map((r) => r.summary.end_datetime || '')
          return {
            final_pnl: sumFinalPnl,
            num_bars: sumBars,
            max_drawdown_amount: minDrawdownRun.summary.max_drawdown_amount,
            max_drawdown_datetime: minDrawdownRun.summary.max_drawdown_datetime,
            max_profit_amount: maxProfitRun.summary.max_profit_amount,
            max_profit_datetime: maxProfitRun.summary.max_profit_datetime,
            start_datetime: starts.length ? starts.reduce((a, b) => (a <= b ? a : b)) : '',
            end_datetime: ends.length ? ends.reduce((a, b) => (a >= b ? a : b)) : '',
          }
        })()
      : null

  const toggleExpiryForCombine = (expiryDate) => {
    setSelectedExpiriesForCombine((prev) =>
      prev.includes(expiryDate) ? prev.filter((e) => e !== expiryDate) : [...prev, expiryDate]
    )
  }

  const selectAllSavedExpiries = () => {
    const dates = runsForUnderlying.map((r) => r.expiry_date)
    setSelectedExpiriesForCombine((prev) =>
      prev.length === dates.length ? [] : dates
    )
  }

  const clearSavedData = () => {
    if (typeof window === 'undefined' || !window.confirm('Clear all saved backtest runs? This cannot be undone.')) return
    setSavedRuns([])
    setSelectedExpiriesForCombine([])
    localStorage.setItem(STORAGE_KEY, '[]')
  }

  return (
    <div className="app">
      <h1>Upstox Backtest</h1>

      <section className="card card-token">
        <h2>API</h2>
        {!showTokenForm ? (
          <>
            <button type="button" onClick={() => setShowTokenForm(true)} className="btn-secondary">
              Update API token
            </button>
            {tokenSaved && <span className="token-saved-msg">Token updated</span>}
          </>
        ) : (
          <div className="token-form-block">
            <label>
              Upstox access token
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Paste your Upstox API access token"
                className="input-full"
              />
            </label>
            <div className="token-form-actions">
              <button onClick={saveToken} disabled={loading} className="btn-secondary">
                {loading ? 'Saving…' : 'Save token'}
              </button>
              <button type="button" onClick={() => setShowTokenForm(false)} className="btn-ghost">
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="card">
        <h2>Expiry dates</h2>
        <p className="section-hint">Set the date range and fetch available expiries before running a backtest.</p>
        <div className="form-grid form-grid-compact">
          <label>
            From date
            <input type="date" value={expiryFromDate} onChange={(e) => setExpiryFromDate(e.target.value)} />
          </label>
          <label>
            To date
            <input type="date" value={expiryToDate} onChange={(e) => setExpiryToDate(e.target.value)} />
          </label>
          <div className="form-grid-button-wrap">
            <button type="button" onClick={fetchExpiries} disabled={expiriesLoading || !config.underlying_key || !expiryFromDate || !expiryToDate} className="btn-secondary">
              {expiriesLoading ? 'Fetching…' : 'Fetch / update expiries'}
            </button>
          </div>
        </div>
        {(expiriesError || expiriesMessage) && (
          <div className="expiries-note">
            {expiriesError && <div className="expiries-error">{expiriesError}</div>}
            {expiriesMessage && <div className="expiries-message">{expiriesMessage}</div>}
          </div>
        )}
      </section>

      <section className="card">
        <h2>Backtest config</h2>
        <div className="form-grid">
          <label>Entry day
            <select value={config.entry_day ?? 0} onChange={(e) => updateConfig('entry_day', Number(e.target.value))}>
              {DAYS.map((day, i) => (
                <option key={day} value={i}>{day}</option>
              ))}
            </select>
          </label>
          <label>Entry time <input type="time" value={config.entry_time ?? '13:15'} onChange={(e) => updateConfig('entry_time', e.target.value)} /></label>
          
          <br/>
        
          
          <label>Exit day
            <select value={config.exit_day ?? 2} onChange={(e) => updateConfig('exit_day', Number(e.target.value))}>
              {DAYS.map((day, i) => (
                <option key={day} value={i}>{day}</option>
              ))}
            </select>
          </label>
          <label>Exit time <input type="time" value={config.exit_time ?? '14:10'} onChange={(e) => updateConfig('exit_time', e.target.value)} /></label>
          <br/>
          <label>Expiry date
            <select
              value={expiries.length && expiries.includes(config.expiry_date) ? config.expiry_date : ''}
              onChange={(e) => updateConfig('expiry_date', e.target.value)}
              disabled={expiriesLoading || !expiries.length}
            >
              {!expiries.length && <option value="">{expiriesLoading ? 'Loading…' : 'No expiries in range'}</option>}
              {expiries.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>
          <label>Underlying key
            <input readOnly value={config.underlying_key} />
          </label>
          <br/>
          <br/>
          <label>First Entry<input type="number" step="0.1" value={config.target_premium} onChange={(e) => updateConfig('target_premium', e.target.value)} /></label>

          <label>Hedge difference <input type="number" value={config.hedge_difference ?? ''} onChange={(e) => updateConfig('hedge_difference', e.target.value)} placeholder="or empty" /></label>
          <br/>
          <br/>
          
          <label>Adjustment 1 <input type="number" step="0.1" value={config.phase2_trigger_premium ?? ''} onChange={(e) => updateConfig('phase2_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Adjustment 1 reentry <input type="number" step="0.1" value={config.phase2_target_reentry} onChange={(e) => updateConfig('phase2_target_reentry', e.target.value)} /></label>
          

          <br />
          <br />
          <label>Adjustment 2<input type="number" step="0.1" value={config.phase2b_trigger_premium ?? ''} onChange={(e) => updateConfig('phase2b_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Adjustment 2 re-entry <input type="number" step="0.1" value={config.phase2b_target_reentry} onChange={(e) => updateConfig('phase2b_target_reentry', e.target.value)} /></label>
          <br />
          <br />
          <label>Adjustment 3 <input type="number" step="0.1" value={config.phase2c_trigger_premium ?? ''} onChange={(e) => updateConfig('phase2c_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Adjustment 3 reentry <input type="number" step="0.1" value={config.phase2c_target_reentry} onChange={(e) => updateConfig('phase2c_target_reentry', e.target.value)} /></label>
          <br />
          <br />
          <label>Adjustment 4 <input type="number" step="0.1" value={config.phase3_trigger_premium ?? ''} onChange={(e) => updateConfig('phase3_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Adjustment 4 reentry <input type="number" step="0.1" value={config.phase3_target_reentry} onChange={(e) => updateConfig('phase3_target_reentry', e.target.value)} /></label>
          <br />
          <br />
          <label>Adjustment 5 CLose Pos <input type="number" step="0.1" value={config.phase4_trigger_premium ?? ''} onChange={(e) => updateConfig('phase4_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          
          
          <label>Stoploss amount <input type="number" value={config.stoploss_amount ?? ''} onChange={(e) => updateConfig('stoploss_amount', e.target.value)} placeholder="or empty" /></label>
          <label>Margin <input type="number" value={config.margin ?? ''} onChange={(e) => updateConfig('margin', e.target.value)} placeholder="e.g. 100000" /></label>
          <label>Profit % <input type="number" step="0.1" value={config.profit_pct ?? ''} onChange={(e) => updateConfig('profit_pct', e.target.value)} placeholder="e.g. 10" /></label>
          <label>Profit amount (₹) <input type="number" readOnly value={(() => { const m = config.margin !== '' && config.margin != null ? Number(config.margin) : null; const p = config.profit_pct !== '' && config.profit_pct != null ? Number(config.profit_pct) : null; return (m != null && p != null && m > 0 && !Number.isNaN(m) && !Number.isNaN(p)) ? (m * p / 100) : ''; })()} placeholder="margin × profit %" /></label>
          <label>Lot size <input type="number" min={1} value={config.lot_size ?? ''} onChange={(e) => updateConfig('lot_size', e.target.value)} placeholder="override instrument lot" /></label>
        </div>
        <button
          onClick={runBacktest}
          disabled={backtestLoading || expiriesLoading || !expiries.length || !expiries.includes(config.expiry_date)}
          className="primary"
          style={{ marginTop: 12 }}
        >
          {backtestLoading ? 'Running backtest…' : 'Run backtest'}
        </button>
      </section>

      {error && <div className="error">{error}</div>}

      {(data.length > 0 && columns.length > 0) && (
        <section className="card table-section">
          <h2>Results</h2>
          {summary && Object.keys(summary).length > 0 && (
            <>
              <div className="results-summary">
                <h3>Summary</h3>
                <dl>
                  <dt>Max drawdown</dt>
<dd>₹{Number(summary.max_drawdown_amount).toFixed(2)} at {formatDateTime(summary.max_drawdown_datetime)}</dd>
                <dt>Max profit</dt>
                <dd>₹{Number(summary.max_profit_amount).toFixed(2)} at {formatDateTime(summary.max_profit_datetime)}</dd>
                <dt>Final PnL</dt>
                <dd>₹{Number(summary.final_pnl).toFixed(2)}</dd>
                <dt>Start</dt>
                <dd>{formatDateTime(summary.start_datetime)}</dd>
                <dt>End</dt>
                <dd>{formatDateTime(summary.end_datetime)}</dd>
                  <dt>Bars</dt>
                  <dd>{summary.num_bars}</dd>
                </dl>
              </div>
              <button type="button" onClick={saveRun} className="save-run-btn btn-secondary" style={{ marginBottom: 12 }}>
                Save run
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => setShowGraph((s) => !s)}
            className="save-run-btn btn-secondary"
            style={{ marginBottom: 12 }}
          >
            {showGraph ? 'Show table' : 'Show graph'}
          </button>
          {showGraph && (() => {
            const chartData = data.filter((row) => row.total_pnl != null)
            if (chartData.length === 0) return null
            const hasNetLegs = chartData[0]?.net_call_leg_pnl != null
            const marginNum = config.margin !== '' && config.margin != null ? Number(config.margin) : null
            const profitPctNum = config.profit_pct !== '' && config.profit_pct != null ? Number(config.profit_pct) : null
            const profitTarget = marginNum != null && profitPctNum != null && marginNum > 0 ? marginNum * (profitPctNum / 100) : null
            const chartHeight = 400
            return (
              <div className="graph-full-width" style={{ height: chartHeight, minHeight: chartHeight, marginBottom: 16, position: 'relative' }}>
                <div className="chart-y-label" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%) rotate(-90deg)', whiteSpace: 'nowrap', fontSize: '0.875rem', color: 'var(--chart-text, #666)', zIndex: 1 }}>
                  PnL (₹)
                </div>
                <ResponsiveContainer width="100%" height={chartHeight}>
                  <LineChart data={chartData} margin={{ top: 8, right: 8, left: 88, bottom: 72 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="timestamp" tick={false} />
                    <YAxis width={70} tickFormatter={(v) => `₹${Number(v).toFixed(0)}`}>
                      <Label value="PnL (₹)" angle={-90} position="insideLeft" style={{ textAnchor: 'middle' }} />
                    </YAxis>
                    <Tooltip
                      labelFormatter={(v) => formatDateTime(v)}
                      formatter={(value, name) => [`₹${Number(value).toFixed(2)}`, name ?? 'PnL']}
                    />
                    <Legend />
                    {profitTarget != null && (
                      <ReferenceLine y={profitTarget} stroke="black" label={{ value: 'Profit amount', position: 'right' }} />
                    )}
                    <Line type="monotone" dataKey="total_pnl" name="Total PnL" stroke="var(--primary-color, #2563eb)" strokeWidth={4} dot={false} />
                    {hasNetLegs && (
                      <>
                        <Line type="monotone" dataKey="net_call_leg_pnl" name="Net call leg" stroke="#16a34a" strokeWidth={2} dot={false} />
                        <Line type="monotone" dataKey="net_put_leg_pnl" name="Net put leg" stroke="#ca8a04" strokeWidth={2} dot={false} />
                      </>
                    )}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )
          })()}
          {!showGraph && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {columns.map((col) => (
                    <th key={col}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((row, i) => {
                  const prev = i > 0 ? data[i - 1] : null
                  const phaseChanged = prev && (
                    (row.phase_ce != null && row.phase_ce !== prev.phase_ce) ||
                    (row.phase_pe != null && row.phase_pe !== prev.phase_pe)
                  )
                  return (
                    <tr key={i} className={phaseChanged ? 'phase-change' : ''}>
                      {columns.map((col) => (
                        <td key={col}>
                          {row[col] != null
                            ? col === 'timestamp'
                              ? formatDateTime(row[col])
                              : String(row[col])
                            : ''}
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          )}
        </section>
      )}

      {runsForUnderlying.length > 0 && (
        <section className="card combined-results-section">
          <div className="combined-results-header">
            <h2>Combined results</h2>
            <button type="button" onClick={clearSavedData} className="clear-saved-btn">
              Clear saved data
            </button>
          </div>
          <p className="combined-hint">Select one or more saved expiries to see combined summary and per-expiry table.</p>
          <div className="combined-expiry-select">
            <button type="button" onClick={selectAllSavedExpiries} className="select-all-expiries-btn">
              {selectedExpiriesForCombine.length === runsForUnderlying.length ? 'Deselect all' : 'Select all'}
            </button>
            <div className="expiry-checkboxes">
              {runsForUnderlying.map((r) => (
                <label key={`${r.underlying_key}-${r.expiry_date}`} className="expiry-checkbox-label">
                  <input
                    type="checkbox"
                    checked={selectedExpiriesForCombine.includes(r.expiry_date)}
                    onChange={() => toggleExpiryForCombine(r.expiry_date)}
                  />
                  <span>{r.expiry_date}</span>
                </label>
              ))}
            </div>
          </div>
          {selectedRuns.length > 0 && combinedSummary && (
            <>
              <div className="results-summary combined-summary">
                <h3>Combined summary</h3>
                <dl>
                  <dt>Max drawdown</dt>
                  <dd>₹{Number(combinedSummary.max_drawdown_amount).toFixed(2)} at {formatDateTime(combinedSummary.max_drawdown_datetime)}</dd>
                  <dt>Max profit</dt>
                  <dd>₹{Number(combinedSummary.max_profit_amount).toFixed(2)} at {formatDateTime(combinedSummary.max_profit_datetime)}</dd>
                  <dt>Final PnL</dt>
                  <dd>₹{Number(combinedSummary.final_pnl).toFixed(2)}</dd>
                  <dt>Start</dt>
                  <dd>{formatDateTime(combinedSummary.start_datetime)}</dd>
                  <dt>End</dt>
                  <dd>{formatDateTime(combinedSummary.end_datetime)}</dd>
                  <dt>Bars</dt>
                  <dd>{combinedSummary.num_bars}</dd>
                </dl>
              </div>
              <div className="table-wrap combined-expiry-table-wrap">
                <table className="combined-expiry-table">
                  <thead>
                    <tr>
                      <th>Expiry</th>
                      <th>Final PnL</th>
                      <th>Max drawdown</th>
                      <th>Max profit</th>
                      <th>Bars</th>
                      <th>Start</th>
                      <th>End</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRuns.map((r) => (
                      <tr key={`${r.underlying_key}-${r.expiry_date}`}>
                        <td>{r.expiry_date}</td>
                        <td>₹{Number(r.summary.final_pnl).toFixed(2)}</td>
                        <td>₹{Number(r.summary.max_drawdown_amount).toFixed(2)} at {formatDateTime(r.summary.max_drawdown_datetime)}</td>
                        <td>₹{Number(r.summary.max_profit_amount).toFixed(2)} at {formatDateTime(r.summary.max_profit_datetime)}</td>
                        <td>{r.summary.num_bars}</td>
                        <td>{formatDateTime(r.summary.start_datetime)}</td>
                        <td>{formatDateTime(r.summary.end_datetime)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  )
}

export default App
