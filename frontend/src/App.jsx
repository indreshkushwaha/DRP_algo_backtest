import { useState, useEffect } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'

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
  phase3_trigger_premium: 98,
  phase3_target_reentry: 50,
  phase4_trigger_premium: 115,
  phase4_target_reentry: 50,
  stoploss_amount: 5000,
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

  useEffect(() => {
    setSavedRuns(loadSavedRuns())
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
    fetch(`${API_BASE}/api/config/token`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: token }),
    })
      .then((r) => {
        if (!r.ok) throw new Error('Failed to save token')
        setTokenSaved(true)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  const runBacktest = () => {
    setError('')
    setData([])
    setColumns([])
    setSummary(null)
    setBacktestLoading(true)
    const body = {
      ...config,
      entry_datetime: computeEntryDatetime(
        config.expiry_date,
        config.entry_day ?? 0,
        config.entry_time ?? '13:15',
      ),
      hedge_difference: config.hedge_difference === '' ? null : Number(config.hedge_difference),
      square_off_when_short_below: config.square_off_when_short_below === '' ? null : Number(config.square_off_when_short_below),
      phase2_trigger_premium: config.phase2_trigger_premium === '' ? null : Number(config.phase2_trigger_premium),
      phase3_trigger_premium: config.phase3_trigger_premium === '' ? null : Number(config.phase3_trigger_premium),
      phase4_trigger_premium: config.phase4_trigger_premium === '' ? null : Number(config.phase4_trigger_premium),
      stoploss_amount: config.stoploss_amount === '' ? null : Number(config.stoploss_amount),
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

      <section className="card">
        <h2>Settings</h2>
        <label>
          Upstox access token
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Paste your Upstox API access token"
            style={{ width: '100%', marginTop: 4, padding: 8 }}
          />
        </label>
        <button onClick={saveToken} disabled={loading} style={{ marginTop: 8 }}>
          {loading ? 'Saving…' : 'Save token'}
        </button>
        {tokenSaved && <span style={{ marginLeft: 8, color: 'green' }}>Saved.</span>}
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
          <label>Target premium <input type="number" step="0.1" value={config.target_premium} onChange={(e) => updateConfig('target_premium', e.target.value)} /></label>
          <label>From date
            <input type="date" value={expiryFromDate} onChange={(e) => setExpiryFromDate(e.target.value)} />
          </label>
          <label>To date
            <input type="date" value={expiryToDate} onChange={(e) => setExpiryToDate(e.target.value)} />
          </label>
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
          <label>
            <button type="button" onClick={fetchExpiries} disabled={expiriesLoading || !config.underlying_key || !expiryFromDate || !expiryToDate}>
              {expiriesLoading ? 'Fetching…' : 'Fetch / update expiries'}
            </button>
          </label>
          {(expiriesError || expiriesMessage) && (
            <div className="expiries-note" style={{ gridColumn: '1 / -1', fontSize: '0.9rem', marginTop: -4 }}>
              {expiriesError && <div className="expiries-error" style={{ color: 'var(--error-color, #ff6b6b)' }}>{expiriesError}</div>}
              {expiriesMessage && <div className="expiries-message" style={{ color: 'var(--message-color, #888)' }}>{expiriesMessage}</div>}
            </div>
          )}
          <label>Underlying key
            <input readOnly value={config.underlying_key} />
          </label>
          <label>Tolerance <input type="number" step="0.1" value={config.tolerance} onChange={(e) => updateConfig('tolerance', e.target.value)} /></label>
          <label>Hedge difference <input type="number" value={config.hedge_difference ?? ''} onChange={(e) => updateConfig('hedge_difference', e.target.value)} placeholder="or empty" /></label>
          <label>Square off when short below <input type="number" step="0.1" value={config.square_off_when_short_below ?? ''} onChange={(e) => updateConfig('square_off_when_short_below', e.target.value)} placeholder="or empty" /></label>
          <label>Phase2 trigger premium <input type="number" step="0.1" value={config.phase2_trigger_premium ?? ''} onChange={(e) => updateConfig('phase2_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Phase2 target reentry <input type="number" step="0.1" value={config.phase2_target_reentry} onChange={(e) => updateConfig('phase2_target_reentry', e.target.value)} /></label>
          <label>Phase2 strike range <input type="number" value={config.phase2_strike_range} onChange={(e) => updateConfig('phase2_strike_range', e.target.value)} /></label>
          <label>Phase3 trigger premium <input type="number" step="0.1" value={config.phase3_trigger_premium ?? ''} onChange={(e) => updateConfig('phase3_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Phase3 target reentry <input type="number" step="0.1" value={config.phase3_target_reentry} onChange={(e) => updateConfig('phase3_target_reentry', e.target.value)} /></label>
          <label>Phase4 trigger premium <input type="number" step="0.1" value={config.phase4_trigger_premium ?? ''} onChange={(e) => updateConfig('phase4_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Stoploss amount <input type="number" value={config.stoploss_amount ?? ''} onChange={(e) => updateConfig('stoploss_amount', e.target.value)} placeholder="or empty" /></label>
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
              <button type="button" onClick={saveRun} className="save-run-btn" style={{ marginBottom: 12 }}>
                Save run
              </button>
            </>
          )}
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
