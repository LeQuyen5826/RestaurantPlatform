import { useEffect, useState } from 'react'
import { api, fmtTime, Reservation, vnd } from '../api'
import { PaymentPanel } from './Booking'

const LABEL: Record<string, string> = {
  pending_deposit: 'Chờ cọc', confirmed: 'Đã xác nhận', checked_in: 'Đã đến', completed: 'Hoàn tất',
  cancelled: 'Đã hủy', expired: 'Hết hạn giữ chỗ', no_show: 'Vắng mặt',
}
const REFUND: Record<string, string> = {
  refund_pending: 'Chờ nhà hàng hoàn cọc', refunded: 'Đã hoàn cọc', forfeited: 'Cọc không được hoàn',
}

export default function MyReservations() {
  const [rows, setRows] = useState<Reservation[]>([])
  const [msg, setMsg] = useState('')
  const load = () => api<Reservation[]>('/reservations/mine').then(setRows)
  useEffect(() => { load() }, [])

  async function cancel(r: Reservation) {
    const hint = r.payment?.status === 'paid'
      ? 'Bạn đã cọc: hủy sát giờ (trong thời hạn miễn phí hủy của nhà hàng) sẽ KHÔNG được hoàn cọc. Tiếp tục hủy?'
      : 'Hủy đặt bàn này?'
    if (!confirm(hint)) return
    try {
      const out = await api<{ refund: string }>(`/reservations/${r.id}/cancel`, { method: 'POST', body: {} })
      setMsg(REFUND[out.refund] ?? 'Đã hủy')
    } catch (e) { setMsg((e as Error).message) }
    load()
  }

  return (
    <>
      <h1>Đặt bàn của tôi</h1>
      {msg && <p className="muted">{msg}</p>}
      {rows.length === 0 && <p className="muted">Chưa có đặt bàn nào.</p>}
      {rows.map((r) => (
        <div className="card" key={r.id}>
          <div className="row">
            <b>#{r.id} · {fmtTime(r.start_at)} · {r.party_size} người · {r.table}</b>
            <span className="badge">{LABEL[r.status] ?? r.status}</span>
            {r.deposit_amount > 0 && <span className="muted">Cọc {vnd(r.deposit_amount)}</span>}
            {r.payment && REFUND[r.payment.refund_status] && <span className="badge">{REFUND[r.payment.refund_status]}</span>}
          </div>
          <PaymentPanel reservation={r} onChange={(n) => setRows((p) => p.map((x) => (x.id === n.id ? n : x)))} />
          {['pending_deposit', 'confirmed'].includes(r.status) && (
            <button className="secondary" onClick={() => cancel(r)}>Hủy đặt bàn</button>
          )}
        </div>
      ))}
    </>
  )
}
