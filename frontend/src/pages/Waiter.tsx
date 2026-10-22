import { useCallback, useEffect, useState } from 'react'
import { api, connectWs, fmtTime, getToken, OrderLine, Reservation, vnd } from '../api'

interface OpenSession { session_id: number; table: string; table_id: number; total: number; items: OrderLine[] }
interface TableRow { id: number; name: string; capacity: number }

export default function Waiter() {
  const [res, setRes] = useState<Reservation[]>([])
  const [sessions, setSessions] = useState<OpenSession[]>([])
  const [tables, setTables] = useState<TableRow[]>([])
  const [openId, setOpenId] = useState('')
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setRes(await api<Reservation[]>('/reservations/today'))
    setSessions(await api<OpenSession[]>('/sessions/open'))
  }, [])
  useEffect(() => {
    load()
    api<TableRow[]>('/tables').then(setTables)
    return connectWs(getToken()!, () => load())
  }, [load])

  const act = async (p: Promise<unknown>) => { try { await p; setErr('') } catch (e) { setErr((e as Error).message) } load() }

  return (
    <>
      <h1>Phục vụ</h1>
      {err && <p className="error">{err}</p>}
      <h2>Đặt bàn hôm nay</h2>
      {res.length === 0 && <p className="muted">Không có đặt bàn.</p>}
      {res.map((r) => (
        <div className="card row" key={r.id}>
          <b>{fmtTime(r.start_at)} · {r.table} · {r.party_size} người</b>
          <span className="badge">{r.status}</span>
          {r.status === 'confirmed' && <button onClick={() => act(api(`/reservations/${r.id}/check-in`, { method: 'POST', body: {} }))}>Check-in & mở bàn</button>}
          {r.status === 'confirmed' && <button className="secondary" onClick={() => act(api(`/reservations/${r.id}/no-show`, { method: 'POST', body: {} }))}>No-show</button>}
          {['pending_deposit', 'confirmed'].includes(r.status) && (
            <select defaultValue="" onChange={(e) => e.target.value && act(api(`/reservations/${r.id}/assign-table`, { body: { table_id: +e.target.value } }))}>
              <option value="">Đổi bàn…</option>
              {tables.filter((t) => t.capacity >= r.party_size).map((t) => <option key={t.id} value={t.id}>{t.name} ({t.capacity})</option>)}
            </select>
          )}
        </div>
      ))}

      <h2>Bàn đang phục vụ</h2>
      <div className="row card">
        <select value={openId} onChange={(e) => setOpenId(e.target.value)}>
          <option value="">Mở bàn cho khách vãng lai…</option>
          {tables.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <button disabled={!openId} onClick={() => act(api('/sessions/open', { body: { table_id: +openId } }))}>Mở bàn</button>
      </div>
      <div className="cols">{sessions.map((s) => (
        <div className="card" key={s.session_id}>
          <h3>{s.table} · {vnd(s.total)}</h3>
          {s.items.map((i) => (
            <div className="row" key={i.id}>
              <span style={{ flex: 1 }}>{i.qty}× {i.name} <span className="badge">{i.status}</span></span>
              {i.status === 'ready' && <button onClick={() => act(api(`/order-items/${i.id}/status`, { method: 'PATCH', body: { status: 'served' } }))}>Đã bưng</button>}
              {i.status !== 'served' && <button className="secondary" onClick={() => act(api(`/order-items/${i.id}/cancel`, { method: 'POST', body: {} }))}>Hủy</button>}
            </div>
          ))}
          <button onClick={() => confirm('Đóng bàn và chốt hóa đơn?') && act(api(`/sessions/${s.session_id}/close`, { method: 'POST', body: {} }))}>Đóng bàn / thu ngân</button>
        </div>
      ))}</div>
    </>
  )
}
