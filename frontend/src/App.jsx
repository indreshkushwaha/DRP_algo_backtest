import { useState, useEffect } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'

const defaultConfig = {
  entry_datetime: '2025-07-25 14:50:00',
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
  phase3_target_reentry: 45,
  phase4_trigger_premium: 115,
  phase4_target_reentry: 65,
  stoploss_amount: 5000,
}

function App() {
  const [token, setToken] = useState('')
  const [tokenSaved, setTokenSaved] = useState(false)
  const [config, setConfig] = useState(defaultConfig)
  const [data, setData] = useState([])
  const [columns, setColumns] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [backtestLoading, setBacktestLoading] = useState(false)

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
    setBacktestLoading(true)
    const body = {
      ...config,
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
      })
      .catch((e) => setError(e.message || 'Backtest failed'))
      .finally(() => setBacktestLoading(false))
  }

  const updateConfig = (key, value) => {
    setConfig((c) => ({ ...c, [key]: value }))
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
          <label>Entry datetime <input value={config.entry_datetime} onChange={(e) => updateConfig('entry_datetime', e.target.value)} /></label>
          <label>Target premium <input type="number" step="0.1" value={config.target_premium} onChange={(e) => updateConfig('target_premium', e.target.value)} /></label>
          <label>Expiry date <input value={config.expiry_date} onChange={(e) => updateConfig('expiry_date', e.target.value)} /></label>
          <label>Underlying key <input value={config.underlying_key} onChange={(e) => updateConfig('underlying_key', e.target.value)} /></label>
          <label>Option type
            <select value={config.option_type} onChange={(e) => updateConfig('option_type', e.target.value)}>
              <option value="CE">CE</option>
              <option value="PE">PE</option>
            </select>
          </label>
          <label>Strike gap <input type="number" value={config.strike_gap} onChange={(e) => updateConfig('strike_gap', e.target.value)} /></label>
          <label>Tolerance <input type="number" step="0.1" value={config.tolerance} onChange={(e) => updateConfig('tolerance', e.target.value)} /></label>
          <label>Hedge difference <input type="number" value={config.hedge_difference ?? ''} onChange={(e) => updateConfig('hedge_difference', e.target.value)} placeholder="or empty" /></label>
          <label>Square off when short below <input type="number" step="0.1" value={config.square_off_when_short_below ?? ''} onChange={(e) => updateConfig('square_off_when_short_below', e.target.value)} placeholder="or empty" /></label>
          <label><input type="checkbox" checked={config.short_pair} onChange={(e) => updateConfig('short_pair', e.target.checked)} /> Short pair (CE+PE)</label>
          <label>Phase2 trigger premium <input type="number" step="0.1" value={config.phase2_trigger_premium ?? ''} onChange={(e) => updateConfig('phase2_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Phase2 target reentry <input type="number" step="0.1" value={config.phase2_target_reentry} onChange={(e) => updateConfig('phase2_target_reentry', e.target.value)} /></label>
          <label>Phase2 strike range <input type="number" value={config.phase2_strike_range} onChange={(e) => updateConfig('phase2_strike_range', e.target.value)} /></label>
          <label>Phase3 trigger premium <input type="number" step="0.1" value={config.phase3_trigger_premium ?? ''} onChange={(e) => updateConfig('phase3_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Phase3 target reentry <input type="number" step="0.1" value={config.phase3_target_reentry} onChange={(e) => updateConfig('phase3_target_reentry', e.target.value)} /></label>
          <label>Phase4 trigger premium <input type="number" step="0.1" value={config.phase4_trigger_premium ?? ''} onChange={(e) => updateConfig('phase4_trigger_premium', e.target.value)} placeholder="or empty" /></label>
          <label>Phase4 target reentry <input type="number" step="0.1" value={config.phase4_target_reentry} onChange={(e) => updateConfig('phase4_target_reentry', e.target.value)} /></label>
          <label>Stoploss amount <input type="number" value={config.stoploss_amount ?? ''} onChange={(e) => updateConfig('stoploss_amount', e.target.value)} placeholder="or empty" /></label>
        </div>
        <button onClick={runBacktest} disabled={backtestLoading} className="primary" style={{ marginTop: 12 }}>
          {backtestLoading ? 'Running backtest…' : 'Run backtest'}
        </button>
      </section>

      {error && <div className="error">{error}</div>}

      {(data.length > 0 && columns.length > 0) && (
        <section className="card table-section">
          <h2>Results</h2>
          <details className="phase-help">
            <summary>When do phases change? (CE vs PE)</summary>
            <div className="phase-help-content">
              <p><strong>phase_ce</strong> (call pair phase) advances when <strong>short PE</strong> (put premium) exceeds the trigger. The backtest then <em>covers the call pair</em>, realizes that PnL, and <em>re-enters a new call pair</em> at the re-entry target premium. So a higher put premium triggers a call-side re-entry.</p>
              <p><strong>phase_pe</strong> (put pair phase) advances when <strong>short CE</strong> (call premium) exceeds the trigger. The backtest <em>covers the put pair</em>, realizes that PnL, and <em>re-enters a new put pair</em> at the re-entry target. So a higher call premium triggers a put-side re-entry.</p>
              <p>Triggers: Phase 2 = first trigger (e.g. 68), Phase 3 = second trigger (e.g. 98). When the short leg exceeds the Phase 4 trigger (e.g. 115), that pair is <em>squared off</em> (no re-entry); PnL for that leg stays 0 afterward. Rows with a thick border in the table are where phase_ce or phase_pe changed.</p>
            </div>
          </details>
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
                        <td key={col}>{row[col] != null ? String(row[col]) : ''}</td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

export default App
