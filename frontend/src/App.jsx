import { useState } from 'react'

const API_BASE = ''

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Expiry weekday (0=Mon .. 6=Sun) by underlying. BSE SENSEX = Tue; Nifty/Bank Nifty = Thu; etc.
function expiryWeekdayForUnderlying(underlyingKey) {
  const k = (underlyingKey || '').toUpperCase()
  if (k.includes('SENSEX') || k.includes('BSE_INDEX')) return 1   // Tuesday
  if (k.includes('NIFTY') || k.includes('BANKNIFTY') || k.includes('FINNIFTY') || k.includes('MIDCPNIFTY')) return 3  // Thursday
  if (k.includes('NSE_INDEX')) return 3  // NSE indices typically Thursday
  return 1  // default Tuesday
}

export default function App() {
  const [activeTab, setActiveTab] = useState('single')

  // ---- Single backtest state ----
  const [instruments, setInstruments] = useState([
    { instrument_key: '', side: 'SELL', lot_size: 20 }
  ])
  const [entryDatetime, setEntryDatetime] = useState('2025-07-25T09:20')
  const [expiryDatetime, setExpiryDatetime] = useState('2025-07-29T15:30')
  const [squareOff, setSquareOff] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  // ---- Date-range backtest state ----
  const [drLoading, setDrLoading] = useState(false)
  const [drError, setDrError] = useState(null)
  const [drResult, setDrResult] = useState(null)
  const [drParams, setDrParams] = useState({
    start_date: '2025-08-15',
    end_date: '2025-08-31',
    expiry_weekday: 1,
    entry_days_before_expiry: 4,
    entry_time: '14:50:00',
    target_premium: 50,
    underlying_key: 'BSE_INDEX|SENSEX',
    option_type: 'CE',
    strike_gap: 100,
    tolerance: 5,
    hedge_difference: 300,
    square_off_short_below: '',
    short_pair: true,
    phase2_trigger_premium: 68,
    phase2_target_reentry: 50,
    phase2_strike_range: 15,
    phase3_trigger_premium: 98,
    phase3_target_reentry: 45,
    phase4_trigger_premium: 115,
    phase4_target_reentry: 65,
    stoploss_amount: 5000,
    delay_between_expiries_seconds: 30
  })

  const updateDr = (field, value) => {
    setDrParams((p) => {
      const next = { ...p, [field]: value }
      if (field === 'underlying_key') {
        next.expiry_weekday = expiryWeekdayForUnderlying(value)
      }
      return next
    })
  }
  const setDrNum = (field, value) => {
    const v = value === '' ? '' : Number(value)
    setDrParams((p) => ({ ...p, [field]: v }))
  }

  const addInstrument = () => {
    setInstruments([...instruments, { instrument_key: '', side: 'SELL', lot_size: 20 }])
  }
  const removeInstrument = (i) => {
    if (instruments.length <= 1) return
    setInstruments(instruments.filter((_, idx) => idx !== i))
  }
  const updateInstrument = (i, field, value) => {
    const next = [...instruments]
    next[i] = { ...next[i], [field]: field === 'lot_size' ? Number(value) || 0 : value }
    setInstruments(next)
  }

  const formatForApi = (s) => s.replace('T', ' ').slice(0, 19)

  const runBacktest = async () => {
    setError(null)
    setResult(null)
    const body = {
      instruments: instruments.map(({ instrument_key, side, lot_size }) => ({
        instrument_key: instrument_key.trim(),
        side,
        lot_size
      })).filter((i) => i.instrument_key),
      entry_datetime: formatForApi(entryDatetime),
      expiry_datetime: formatForApi(expiryDatetime),
      square_off_short_below: squareOff === '' ? null : Number(squareOff)
    }
    if (!body.instruments.length) {
      setError('Add at least one instrument with instrument_key.')
      return
    }
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || res.statusText || 'Request failed')
        return
      }
      setResult(data)
    } catch (e) {
      setError(e.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }

  const runDateRangeBacktest = async () => {
    setDrError(null)
    setDrResult(null)
    const p = drParams
    if (p.end_date && p.start_date && p.end_date < p.start_date) {
      setDrError('End date must be on or after start date.')
      return
    }
    const body = {
      start_date: p.start_date,
      end_date: p.end_date,
      expiry_weekday: p.expiry_weekday,
      entry_days_before_expiry: p.entry_days_before_expiry,
      entry_time: p.entry_time,
      target_premium: p.target_premium,
      underlying_key: p.underlying_key,
      option_type: p.option_type,
      strike_gap: p.strike_gap,
      tolerance: p.tolerance,
      hedge_difference: p.hedge_difference == null || p.hedge_difference === '' ? null : p.hedge_difference,
      square_off_short_below: p.square_off_short_below == null || p.square_off_short_below === '' ? null : p.square_off_short_below,
      short_pair: p.short_pair,
      phase2_trigger_premium: p.phase2_trigger_premium == null || p.phase2_trigger_premium === '' ? null : p.phase2_trigger_premium,
      phase2_target_reentry: p.phase2_target_reentry,
      phase2_strike_range: p.phase2_strike_range,
      phase3_trigger_premium: p.phase3_trigger_premium == null || p.phase3_trigger_premium === '' ? null : p.phase3_trigger_premium,
      phase3_target_reentry: p.phase3_target_reentry,
      phase4_trigger_premium: p.phase4_trigger_premium == null || p.phase4_trigger_premium === '' ? null : p.phase4_trigger_premium,
      phase4_target_reentry: p.phase4_target_reentry,
      stoploss_amount: p.stoploss_amount == null || p.stoploss_amount === '' ? null : p.stoploss_amount,
      delay_between_expiries_seconds: p.delay_between_expiries_seconds
    }
    setDrLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/backtest/date-range`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setDrError(data.detail || res.statusText || 'Request failed')
        return
      }
      setDrResult(data)
    } catch (e) {
      setDrError(e.message || 'Network error')
    } finally {
      setDrLoading(false)
    }
  }

  const columns = result?.data?.[0] ? Object.keys(result.data[0]) : []
  const drColumns = drResult?.data?.[0] ? Object.keys(drResult.data[0]) : []

  return (
    <div>
      <h1>Weekly Backtest</h1>
      <div style={{ marginBottom: '1rem' }}>
        <button type="button" onClick={() => setActiveTab('single')} disabled={loading || drLoading} style={{ marginRight: '0.5rem', fontWeight: activeTab === 'single' ? 'bold' : 'normal' }}>Single backtest</button>
        <button type="button" onClick={() => setActiveTab('dateRange')} disabled={loading || drLoading} style={{ fontWeight: activeTab === 'dateRange' ? 'bold' : 'normal' }}>Date-range backtest</button>
      </div>

      {activeTab === 'single' && (
        <>
          <section>
            <label>Entry datetime</label>
            <input type="datetime-local" value={entryDatetime} onChange={(e) => setEntryDatetime(e.target.value)} disabled={loading} />
            <label>Expiry datetime</label>
            <input type="datetime-local" value={expiryDatetime} onChange={(e) => setExpiryDatetime(e.target.value)} disabled={loading} />
          </section>
          <section>
            <label>Square off short below (optional)</label>
            <input type="number" placeholder="e.g. 145" value={squareOff} onChange={(e) => setSquareOff(e.target.value)} disabled={loading} />
          </section>
          <section>
            <strong>Instruments</strong>
            {instruments.map((inst, i) => (
              <div key={i} style={{ marginBottom: '0.5rem' }}>
                <input placeholder="instrument_key" value={inst.instrument_key} onChange={(e) => updateInstrument(i, 'instrument_key', e.target.value)} disabled={loading} style={{ width: '320px' }} />
                <select value={inst.side} onChange={(e) => updateInstrument(i, 'side', e.target.value)} disabled={loading}>
                  <option value="SELL">SELL</option>
                  <option value="BUY">BUY</option>
                </select>
                <input type="number" placeholder="lot_size" value={inst.lot_size} onChange={(e) => updateInstrument(i, 'lot_size', e.target.value)} disabled={loading} min={1} />
                <button type="button" onClick={() => removeInstrument(i)} disabled={loading || instruments.length <= 1}>Remove</button>
              </div>
            ))}
            <button type="button" onClick={addInstrument} disabled={loading}>Add instrument</button>
          </section>
          <section style={{ marginTop: '1rem' }}>
            <button onClick={runBacktest} disabled={loading}>
              {loading ? 'Running backtest…' : 'Run backtest'}
            </button>
          </section>
          {error && <p className="error">{error}</p>}
          {result && (
            <>
              <div className="summary">
                <strong>Summary</strong>: row_count = {result.summary?.row_count ?? '—'}, final_pnl = {result.summary?.final_pnl ?? '—'}
              </div>
              <div className="tableWrap">
                <table>
                  <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>
                    {result.data?.map((row, i) => (
                      <tr key={i}>{columns.map((col) => <td key={col}>{row[col] != null ? String(row[col]) : ''}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}

      {activeTab === 'dateRange' && (
        <>
          <section>
            <strong>Date range</strong>
            <div style={{ marginTop: '0.5rem' }}>
              <label>Start date</label>
              <input type="date" value={drParams.start_date} onChange={(e) => updateDr('start_date', e.target.value)} disabled={drLoading} />
              <label>End date</label>
              <input type="date" value={drParams.end_date} onChange={(e) => updateDr('end_date', e.target.value)} disabled={drLoading} />
              <label>Expiry weekday</label>
              <select value={drParams.expiry_weekday} onChange={(e) => updateDr('expiry_weekday', Number(e.target.value))} disabled={drLoading}>
                {WEEKDAYS.map((d, i) => <option key={i} value={i}>{d} ({i})</option>)}
              </select>
              <label>Entry days before expiry</label>
              <input type="number" min={0} value={drParams.entry_days_before_expiry} onChange={(e) => setDrNum('entry_days_before_expiry', e.target.value)} disabled={drLoading} />
              <label>Entry time</label>
              <input type="text" placeholder="14:50:00" value={drParams.entry_time} onChange={(e) => updateDr('entry_time', e.target.value)} disabled={drLoading} />
            </div>
          </section>
          <section>
            <strong>Backtest parameters</strong>
            <div style={{ marginTop: '0.5rem', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.25rem 1rem', maxWidth: '520px' }}>
              <label>Target premium</label>
              <input type="number" step="0.1" value={drParams.target_premium} onChange={(e) => setDrNum('target_premium', e.target.value)} disabled={drLoading} />
              <label>Underlying key</label>
              <input type="text" value={drParams.underlying_key} onChange={(e) => updateDr('underlying_key', e.target.value)} disabled={drLoading} style={{ width: '240px' }} />
              <label>Option type</label>
              <select value={drParams.option_type} onChange={(e) => updateDr('option_type', e.target.value)} disabled={drLoading}>
                <option value="CE">CE</option>
                <option value="PE">PE</option>
              </select>
              <label>Strike gap</label>
              <input type="number" value={drParams.strike_gap} onChange={(e) => setDrNum('strike_gap', e.target.value)} disabled={drLoading} />
              <label>Tolerance</label>
              <input type="number" step="0.1" value={drParams.tolerance} onChange={(e) => setDrNum('tolerance', e.target.value)} disabled={drLoading} />
              <label>Hedge difference</label>
              <input type="number" value={drParams.hedge_difference ?? ''} onChange={(e) => setDrNum('hedge_difference', e.target.value)} placeholder="optional" disabled={drLoading} />
              <label>Square off short below</label>
              <input type="number" value={drParams.square_off_short_below ?? ''} onChange={(e) => setDrNum('square_off_short_below', e.target.value)} placeholder="optional" disabled={drLoading} />
              <label>Short pair</label>
              <input type="checkbox" checked={drParams.short_pair} onChange={(e) => updateDr('short_pair', e.target.checked)} disabled={drLoading} />
              <label>Phase2 trigger premium</label>
              <input type="number" step="0.1" value={drParams.phase2_trigger_premium ?? ''} onChange={(e) => setDrNum('phase2_trigger_premium', e.target.value)} disabled={drLoading} />
              <label>Phase2 target reentry</label>
              <input type="number" step="0.1" value={drParams.phase2_target_reentry} onChange={(e) => setDrNum('phase2_target_reentry', e.target.value)} disabled={drLoading} />
              <label>Phase2 strike range</label>
              <input type="number" value={drParams.phase2_strike_range} onChange={(e) => setDrNum('phase2_strike_range', e.target.value)} disabled={drLoading} />
              <label>Phase3 trigger premium</label>
              <input type="number" step="0.1" value={drParams.phase3_trigger_premium ?? ''} onChange={(e) => setDrNum('phase3_trigger_premium', e.target.value)} disabled={drLoading} />
              <label>Phase3 target reentry</label>
              <input type="number" step="0.1" value={drParams.phase3_target_reentry} onChange={(e) => setDrNum('phase3_target_reentry', e.target.value)} disabled={drLoading} />
              <label>Phase4 trigger premium</label>
              <input type="number" step="0.1" value={drParams.phase4_trigger_premium ?? ''} onChange={(e) => setDrNum('phase4_trigger_premium', e.target.value)} disabled={drLoading} />
              <label>Phase4 target reentry</label>
              <input type="number" step="0.1" value={drParams.phase4_target_reentry} onChange={(e) => setDrNum('phase4_target_reentry', e.target.value)} disabled={drLoading} />
              <label>Stoploss amount</label>
              <input type="number" value={drParams.stoploss_amount ?? ''} onChange={(e) => setDrNum('stoploss_amount', e.target.value)} placeholder="optional" disabled={drLoading} />
              <label>Delay between expiries (s)</label>
              <input type="number" step="0.1" value={drParams.delay_between_expiries_seconds} onChange={(e) => setDrNum('delay_between_expiries_seconds', e.target.value)} disabled={drLoading} />
            </div>
          </section>
          <section style={{ marginTop: '1rem' }}>
            <button onClick={runDateRangeBacktest} disabled={drLoading}>
              {drLoading ? 'Running date-range backtest…' : 'Run date-range backtest'}
            </button>
          </section>
          {drError && <p className="error">{drError}</p>}
          {drResult && (
            <>
              <div className="summary">
                <strong>Summary</strong>: row_count = {drResult.row_count ?? '—'}, combined_pnl = {drResult.summary?.combined_pnl ?? '—'}
              </div>
              {drResult.summary?.per_expiry?.length > 0 && (
                <table style={{ marginTop: '0.5rem', marginBottom: '1rem' }}>
                  <thead><tr><th>Expiry</th><th>Final total PnL</th></tr></thead>
                  <tbody>
                    {drResult.summary.per_expiry.map((row, i) => (
                      <tr key={i}><td>{row.expiry}</td><td>{row.final_total_pnl}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="tableWrap">
                <table>
                  <thead><tr>{drColumns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>
                    {drResult.data?.map((row, i) => (
                      <tr key={i}>{drColumns.map((col) => <td key={col}>{row[col] != null ? String(row[col]) : ''}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
