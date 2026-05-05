import { useState, useEffect, useRef, useCallback } from 'react'
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

const DEFAULT_MARGIN_FOR_PCT = 60000

/** Margin used for % on PnL: positive finite number, else default 60000. */
function effectiveMarginForPct(value) {
  if (value === '' || value == null) return DEFAULT_MARGIN_FOR_PCT
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_MARGIN_FOR_PCT
  return n
}

function extraPctOnMargin(finalPnl, marginField) {
  const m = effectiveMarginForPct(marginField)
  return (Number(finalPnl) / m) * 100
}

function formatExtraPct(finalPnl, marginField) {
  return `${extraPctOnMargin(finalPnl, marginField).toFixed(2)}%`
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
  entry_time: '15:00',
  exit_day: 2,
  exit_time: '15:15',
  target_premium: 50,
  expiry_date: '2025-10-30',
  underlying_key: 'BSE_INDEX|SENSEX',
  option_type: 'CE',
  strike_gap: 100,
  tolerance: 5,
  hedge_difference: 300,
  square_off_when_short_below: 145,
  short_pair: true,
  phase2_trigger_premium: 76,
  phase2_target_reentry: 50,
  phase2_strike_range: 15,
  phase2b_trigger_premium: 98,
  phase2b_target_reentry: 50,
  phase2c_trigger_premium: 115,
  phase2c_target_reentry: 50,
  phase3_trigger_premium: 134,
  phase3_target_reentry: 50,
  phase4_trigger_premium: 150,
  phase4_target_reentry: 50,
  stoploss_amount: 3000,
  margin: '60000',
  profit_pct: '2',
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
  const [tokenStatus, setTokenStatus] = useState(null)
  const [config, setConfig] = useState(defaultConfig)
  const [data, setData] = useState([])
  const [columns, setColumns] = useState([])
  const [summary, setSummary] = useState(null)
  const [backtestLogs, setBacktestLogs] = useState('')
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
  const [loadedSavedExpiryDate, setLoadedSavedExpiryDate] = useState('')
  const [showGraph, setShowGraph] = useState(true)
  const [showTokenForm, setShowTokenForm] = useState(false)
  const [backendHealthy, setBackendHealthy] = useState(false)
  const [hideSensitive, setHideSensitive] = useState(false)
  const [mongoStorageEnabled, setMongoStorageEnabled] = useState(false)
  const [serverStoredRuns, setServerStoredRuns] = useState([])
  const tokenSavedTimeoutRef = useRef(null)

  const refreshServerStoredRuns = useCallback(() => {
    fetch(`${API_BASE}/api/backtest/storage`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        const en = !!d.enabled
        setMongoStorageEnabled(en)
        if (!en) {
          setServerStoredRuns([])
          return null
        }
        return fetch(
          `${API_BASE}/api/backtest/stored?underlying_key=${encodeURIComponent(config.underlying_key)}`,
        ).then((r2) => (r2.ok ? r2.json() : Promise.reject()))
      })
      .then((listBody) => {
        if (listBody && Array.isArray(listBody.runs)) setServerStoredRuns(listBody.runs)
      })
      .catch(() => {
        setMongoStorageEnabled(false)
        setServerStoredRuns([])
      })
  }, [config.underlying_key])

  useEffect(() => {
    refreshServerStoredRuns()
  }, [refreshServerStoredRuns])

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
      .then((r) => {
        if (!r.ok) throw new Error('defaults request failed')
        return r.json()
      })
      .then((d) =>
        setConfig((c) => {
          const next = { ...c }
          for (const [key, val] of Object.entries(d)) {
            if (val == null) continue
            if (key === 'margin' || key === 'profit_pct') {
              next[key] = val === '' ? val : String(val)
              continue
            }
            next[key] = val
          }
          return next
        }),
      )
      .catch(() => {})
    fetch(`${API_BASE}/api/config/token`)
      .then((r) => r.json())
      .then((d) => setToken(d.access_token || ''))
      .catch(() => {})
  }, [])

  useEffect(() => {
    let isActive = true
    const checkBackendHealth = () => {
      fetch(`${API_BASE}/api/health`)
        .then(async (r) => {
          if (!r.ok) throw new Error('Health check failed')
          const body = await r.json()
          if (!isActive) return
          setBackendHealthy(body?.ok === true)
        })
        .catch(() => {
          if (!isActive) return
          setBackendHealthy(false)
        })
    }

    checkBackendHealth()
    const intervalId = setInterval(checkBackendHealth, 10000)
    return () => {
      isActive = false
      clearInterval(intervalId)
    }
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
    setTokenStatus(null)
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
      .then(async (r) => {
        if (!r.ok) throw new Error('Failed to save token')
        const res = await r.json()
        setShowTokenForm(false)
        setTokenStatus({
          tokenValid: !!res.token_valid,
          message: res.message || 'API updated',
          user: res.user || null,
        })
        tokenSavedTimeoutRef.current = setTimeout(() => {
          setTokenStatus(null)
          tokenSavedTimeoutRef.current = null
        }, 5000)
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
    setBacktestLogs('')
    setShowGraph(false)
    setBacktestLoading(true)
    const body = {
      ...config,
      entry_datetime: computeEntryDatetime(
        config.expiry_date,
        config.entry_day ?? 0,
        config.entry_time ?? '15:00',
      ),
      exit_datetime: computeExitDatetime(
        config.expiry_date,
        config.exit_day ?? 2,
        config.exit_time ?? '15:15',
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
        setBacktestLogs(typeof res.logs === 'string' ? res.logs : '')
        refreshServerStoredRuns()
      })
      .catch((e) => setError(e.message || 'Backtest failed'))
      .finally(() => setBacktestLoading(false))
  }

  const updateConfig = (key, value) => {
    if (key === 'lot_size' && value !== '') {
      const num = Number(value)
      if (!Number.isNaN(num) && num < 1) value = 1
    }
    setConfig((c) => {
      if (key !== 'lot_size') {
        return { ...c, [key]: value }
      }
      if (value === '') {
        return { ...c, lot_size: value }
      }
      const n = Number(value)
      if (Number.isNaN(n) || n < 1) {
        return { ...c, lot_size: value }
      }
      return { ...c, lot_size: value, margin: String((n / 20) * 60000) }
    })
  }

  const saveRun = () => {
    if (data.length === 0 || columns.length === 0) return
    const run = {
      underlying_key: config.underlying_key,
      expiry_date: config.expiry_date,
      data: [...data],
      columns: [...columns],
      logs: backtestLogs,
      margin: config.margin === '' ? null : Number(config.margin),
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

  const hydrateRunFromPayload = (run, expiryDate) => {
    setData(Array.isArray(run.data) ? run.data : [])
    setColumns(Array.isArray(run.columns) ? run.columns : [])
    setBacktestLogs(typeof run.logs === 'string' ? run.logs : '')
    setSummary(run.summary ?? null)
    setShowGraph(true)
    setLoadedSavedExpiryDate(expiryDate)
    setConfig((c) => ({
      ...c,
      expiry_date: expiryDate,
      margin:
        run.margin != null && run.margin !== ''
          ? String(run.margin)
          : c.margin,
    }))
  }

  const loadSavedRun = (expiryDate) => {
    const run = savedRuns.find(
      (r) => r.underlying_key === config.underlying_key && r.expiry_date === expiryDate,
    )
    if (!run) return
    hydrateRunFromPayload(run, expiryDate)
  }

  const loadServerRun = (expiryDate) => {
    setError('')
    const url = `${API_BASE}/api/backtest/stored?underlying_key=${encodeURIComponent(config.underlying_key)}&expiry_date=${encodeURIComponent(expiryDate)}`
    fetch(url)
      .then((r) => {
        if (!r.ok) {
          return r.json().then((e) => {
            const msg =
              typeof e.detail === 'string' ? e.detail : Array.isArray(e.detail) ? e.detail.map((x) => x.msg || JSON.stringify(x)).join(', ') : 'Load failed'
            throw new Error(msg)
          })
        }
        return r.json()
      })
      .then((body) => {
        if (body?.run) hydrateRunFromPayload(body.run, expiryDate)
      })
      .catch((e) => setError(e.message || 'Failed to load from server'))
  }

  const deleteServerRun = (expiryDate) => {
    if (
      typeof window === 'undefined' ||
      !window.confirm(`Delete stored run for ${expiryDate}? This cannot be undone.`)
    ) {
      return
    }
    setError('')
    const url = `${API_BASE}/api/backtest/stored?underlying_key=${encodeURIComponent(config.underlying_key)}&expiry_date=${encodeURIComponent(expiryDate)}`
    fetch(url, { method: 'DELETE' })
      .then((r) => {
        if (!r.ok) {
          return r.json().then((e) => {
            const msg =
              typeof e.detail === 'string'
                ? e.detail
                : Array.isArray(e.detail)
                  ? e.detail.map((x) => x.msg || JSON.stringify(x)).join(', ')
                  : 'Delete failed'
            throw new Error(msg)
          })
        }
        return r.json()
      })
      .then(() => {
        setServerStoredRuns((prev) => prev.filter((run) => run.expiry_date !== expiryDate))
        if (loadedSavedExpiryDate === expiryDate) setLoadedSavedExpiryDate('')
      })
      .catch((e) => setError(e.message || 'Failed to delete from server'))
  }

  const runsForUnderlying = savedRuns.filter((r) => r.underlying_key === config.underlying_key)
  const selectedRuns = runsForUnderlying.filter((r) => selectedExpiriesForCombine.includes(r.expiry_date))

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
    setLoadedSavedExpiryDate('')
    localStorage.setItem(STORAGE_KEY, '[]')
  }

  const deleteSavedRun = (expiryDate) => {
    if (
      typeof window === 'undefined' ||
      !window.confirm(`Delete saved run for ${expiryDate}? This cannot be undone.`)
    ) {
      return
    }
    const next = savedRuns.filter(
      (r) => !(r.underlying_key === config.underlying_key && r.expiry_date === expiryDate),
    )
    setSavedRuns(next)
    setSelectedExpiriesForCombine((prev) => prev.filter((e) => e !== expiryDate))
    if (loadedSavedExpiryDate === expiryDate) setLoadedSavedExpiryDate('')
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  }

  return (
    <div className="app">
      <div className="app-header">
        <h1>Upstox Backtest</h1>
        <div className="app-header-actions">
          <button
            type="button"
            onClick={() => setHideSensitive((s) => !s)}
            className="btn-secondary hide-sensitive-btn"
          >
            {hideSensitive ? 'Show sensitive' : 'Hide sensitive'}
          </button>
          <div
            className="backend-health-indicator"
            title={`Backend ${backendHealthy ? 'Online' : 'Offline'}`}
            aria-label={`Backend ${backendHealthy ? 'Online' : 'Offline'}`}
          >
            <span className={`backend-health-dot ${backendHealthy ? 'is-healthy' : 'is-unhealthy'}`} />
          </div>
        </div>
      </div>

      <section className="card card-token">
        <h2>API</h2>
        {!showTokenForm ? (
          <>
            <button type="button" onClick={() => setShowTokenForm(true)} className="btn-secondary">
              Update API token
            </button>
            {tokenStatus && (
              <span className={`token-saved-msg ${tokenStatus.tokenValid ? 'token-status-ok' : 'token-status-warn'}`}>
                {tokenStatus.message}
                {tokenStatus.tokenValid && tokenStatus.user && (
                  <>
                    {' '}
                    {tokenStatus.user.user_name || 'Unknown user'}
                    {tokenStatus.user.user_id ? ` (${tokenStatus.user.user_id})` : ''}
                    {tokenStatus.user.email ? ` - ${tokenStatus.user.email}` : ''}
                  </>
                )}
              </span>
            )}
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

      <section className="card backtest-config-card">
        <h2>Backtest config</h2>
        <div className="form-grid backtest-config-grid">
          <label>
            Entry day
            <select value={config.entry_day ?? 0} onChange={(e) => updateConfig('entry_day', Number(e.target.value))}>
              {DAYS.map((day, i) => (
                <option key={day} value={i}>{day}</option>
              ))}
            </select>
          </label>
          <label>
            Entry time
            <input type="time" value={config.entry_time ?? '15:00'} onChange={(e) => updateConfig('entry_time', e.target.value)} />
          </label>
          <label>
            Exit day
            <select value={config.exit_day ?? 2} onChange={(e) => updateConfig('exit_day', Number(e.target.value))}>
              {DAYS.map((day, i) => (
                <option key={day} value={i}>{day}</option>
              ))}
            </select>
          </label>
          <label>
            Exit time
            <input type="time" value={config.exit_time ?? '15:15'} onChange={(e) => updateConfig('exit_time', e.target.value)} />
          </label>
          <label>
            Expiry date
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
            Underlying key
            <input readOnly value={config.underlying_key} />
          </label>
          <label>
            First entry premium
            <input type="number" step="0.1" value={config.target_premium} onChange={(e) => updateConfig('target_premium', e.target.value)} />
          </label>
          <label>
            Hedge difference
            <input
              type={hideSensitive ? 'text' : 'number'}
              value={hideSensitive ? 'XXX' : (config.hedge_difference ?? '')}
              onChange={(e) => updateConfig('hedge_difference', e.target.value)}
              placeholder="or empty"
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 1 trigger
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : (config.phase2_trigger_premium ?? '')}
              onChange={(e) => updateConfig('phase2_trigger_premium', e.target.value)}
              placeholder="or empty"
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 1 re-entry
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : config.phase2_target_reentry}
              onChange={(e) => updateConfig('phase2_target_reentry', e.target.value)}
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 2 trigger
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : (config.phase2b_trigger_premium ?? '')}
              onChange={(e) => updateConfig('phase2b_trigger_premium', e.target.value)}
              placeholder="or empty"
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 2 re-entry
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : config.phase2b_target_reentry}
              onChange={(e) => updateConfig('phase2b_target_reentry', e.target.value)}
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 3 trigger
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : (config.phase2c_trigger_premium ?? '')}
              onChange={(e) => updateConfig('phase2c_trigger_premium', e.target.value)}
              placeholder="or empty"
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 3 re-entry
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : config.phase2c_target_reentry}
              onChange={(e) => updateConfig('phase2c_target_reentry', e.target.value)}
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 4 trigger
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : (config.phase3_trigger_premium ?? '')}
              onChange={(e) => updateConfig('phase3_trigger_premium', e.target.value)}
              placeholder="or empty"
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 4 re-entry
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : config.phase3_target_reentry}
              onChange={(e) => updateConfig('phase3_target_reentry', e.target.value)}
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Adjustment 5 close position
            <input
              type={hideSensitive ? 'text' : 'number'}
              step={hideSensitive ? undefined : '0.1'}
              value={hideSensitive ? 'XXX' : (config.phase4_trigger_premium ?? '')}
              onChange={(e) => updateConfig('phase4_trigger_premium', e.target.value)}
              placeholder="or empty"
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Stop loss amount
            <input
              type={hideSensitive ? 'text' : 'number'}
              value={hideSensitive ? 'XXX' : (config.stoploss_amount ?? '')}
              onChange={(e) => updateConfig('stoploss_amount', e.target.value)}
              placeholder="or empty"
              readOnly={hideSensitive}
            />
          </label>
          <label>
            Margin
            <input type="number" value={config.margin ?? ''} onChange={(e) => updateConfig('margin', e.target.value)} placeholder="e.g. 60000" />
          </label>
          <label>
            Profit %
            <input type="number" step="0.01" value={config.profit_pct ?? ''} onChange={(e) => updateConfig('profit_pct', e.target.value)} placeholder="e.g. 2" />
          </label>
          <label>
            Profit amount (₹)
            <input type="number" readOnly value={(() => { const m = config.margin !== '' && config.margin != null ? Number(config.margin) : null; const p = config.profit_pct !== '' && config.profit_pct != null ? Number(config.profit_pct) : null; return (m != null && p != null && m > 0 && !Number.isNaN(m) && !Number.isNaN(p)) ? (m * p / 100) : ''; })()} placeholder="margin × profit %" />
          </label>
          <label>
            Qty
            <input type="number" min={1} value={config.lot_size ?? ''} onChange={(e) => updateConfig('lot_size', e.target.value)} placeholder="qty" />
          </label>
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
      {backtestLogs && (
        <section className="card run-log-section">
          <h2>Run log</h2>
          <details open>
            <summary>Backtest execution logs</summary>
            <pre className="backtest-log">{backtestLogs}</pre>
          </details>
        </section>
      )}

      {(data.length > 0 && columns.length > 0) && (
        <section className="card table-section">
          <h2>Results</h2>
          {summary && Object.keys(summary).length > 0 && (
            <div className="results-summary">
              <h3>Summary</h3>
              <dl>
                <dt>Max drawdown</dt>
                <dd>₹{Number(summary.max_drawdown_amount).toFixed(2)} at {formatDateTime(summary.max_drawdown_datetime)}</dd>
                <dt>Max profit</dt>
                <dd>₹{Number(summary.max_profit_amount).toFixed(2)} at {formatDateTime(summary.max_profit_datetime)}</dd>
                <dt>Final PnL</dt>
                <dd>₹{Number(summary.final_pnl).toFixed(2)}</dd>
                <dt>Extra</dt>
                <dd>{formatExtraPct(summary.final_pnl, config.margin)}</dd>
                <dt>Start</dt>
                <dd>{formatDateTime(summary.start_datetime)}</dd>
                <dt>End</dt>
                <dd>{formatDateTime(summary.end_datetime)}</dd>
                <dt>Bars</dt>
                <dd>{summary.num_bars}</dd>
              </dl>
            </div>
          )}
          <button type="button" onClick={saveRun} className="save-run-btn btn-secondary" style={{ marginBottom: 12 }}>
            Save run
          </button>
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
                      formatter={(value, name) => {
                        const n = Number(value)
                        const rupee = `₹${Number.isFinite(n) ? n.toFixed(2) : String(value)}`
                        const withPct =
                          Number.isFinite(n)
                            ? `${rupee} (${formatExtraPct(n, config.margin)})`
                            : rupee
                        return [withPct, name ?? 'PnL']
                      }}
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
            <h2>Saved backtests</h2>
            <button type="button" onClick={clearSavedData} className="clear-saved-btn">
              Clear saved data
            </button>
          </div>
          <p className="combined-hint">Click any saved expiry to load its graph and table into Results.</p>
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
                  <button
                    type="button"
                    onClick={() => loadSavedRun(r.expiry_date)}
                    className="btn-ghost"
                  >
                    {r.expiry_date}
                    {loadedSavedExpiryDate === r.expiry_date ? ' (loaded)' : ''}
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteSavedRun(r.expiry_date)}
                    className="delete-saved-run-btn"
                  >
                    Delete
                  </button>
                </label>
              ))}
            </div>
          </div>
          {selectedRuns.length > 0 && (
            <>
              <div className="table-wrap combined-expiry-table-wrap">
                <table className="combined-expiry-table">
                  <thead>
                    <tr>
                      <th>Expiry</th>
                      <th>Rows</th>
                      <th>Saved at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRuns.map((r) => (
                      <tr key={`${r.underlying_key}-${r.expiry_date}`}>
                        <td>{r.expiry_date}</td>
                        <td>{Array.isArray(r.data) ? r.data.length : 0}</td>
                        <td>{formatDateTime(r.savedAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      )}

      {mongoStorageEnabled && (
        <section className="card combined-results-section">
          <h2>Server-stored backtests (MongoDB)</h2>
          <p className="combined-hint">
            Auto-saved after each successful backtest. Use Load from server to open a run in Results (same shape as local Save run, including summary).
          </p>
          {serverStoredRuns.length === 0 ? (
            <p className="combined-hint">No stored runs for this underlying yet.</p>
          ) : (
            <div className="server-runs-list">
              {serverStoredRuns.map((r) => (
                <div key={`server-${r.expiry_date}`} className="server-run-row">
                  <div className="server-run-main">
                    <button
                      type="button"
                      onClick={() => loadServerRun(r.expiry_date)}
                      className="btn-ghost server-run-expiry-btn"
                    >
                      {r.expiry_date}
                      {loadedSavedExpiryDate === r.expiry_date ? ' (loaded)' : ''}
                    </button>
                    <span className="server-run-meta">
                      {r.row_count != null ? `${r.row_count} rows` : ''}
                      {r.saved_at != null ? ` · ${formatDateTime(r.saved_at)}` : ''}
                      {r.final_pnl != null ? ` · PnL ₹${Number(r.final_pnl).toFixed(2)}` : ''}
                    </span>
                  </div>
                  <div className="server-run-actions">
                    <button
                      type="button"
                      onClick={() => deleteServerRun(r.expiry_date)}
                      className="delete-server-run-btn"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}

export default App
