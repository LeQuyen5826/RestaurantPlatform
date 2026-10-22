import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, connectWs, fmtTime, getToken, Reservation, Slot, vnd } from '../api'
import { useAuth } from '../auth'

const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)

/** Hiển thị QR cọc, tự cập nhật trạng thái (poll 3 giây + WebSocket). */
export function PaymentPanel({ reservation, onChange }: { reservation: Reservation; onChange: (r: Reservation) => void }) {
  const [left, setLeft] = useState(0)

  useEffect(() => {
    if (reservation.status !== 'pending_deposit') return
    const poll = setInterval(async () => onChange(await api<Reservation>(`/reservations/${reservation.id}`)), 3000)
    const token = getToken()
    const close = token
      ? connectWs(token, (m) => m.type === 'deposit_paid' && api<Reservation>(`/reservations/${reservation.id}`).then(onChange))
      : () => {}
    return () => {
      clearInterval(poll)
      close()
    }
  }, [reservation.id, reservation.status])

  useEffect(() => {
    if (!reservation.hold_until) return
    const tick = () => setLeft(Math.max(0, Math.floor((new Date(reservation.hold_until!).getTime() - Date.now()) / 1000)))
    tick()
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
  }, [reservation.hold_until])

  const p = reservation.payment
  if (reservation.status === 'confirmed') return <p className="ok">✅ Đã nhận cọc. Đặt bàn đã xác nhận.</p>
  if (reservation.status === 'expired') return <p className="error">Hết thời gian giữ chỗ. Vui lòng đặt lại.</p>
  if (reservation.status !== 'pending_deposit' || !p) return null
  return (
    <div className="card">
      <h3>Quét QR để đặt cọc {vnd(p.amount)}</h3>
      {p.qr_url && <img src={p.qr_url} alt="VietQR" width={260} />}
      <p>
        Nội dung chuyển khoản (giữ nguyên): <b>{p.code}</b>
      </p>
      <p className="muted">
        Giữ chỗ còn {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')}. Trang tự cập nhật khi nhận được tiền.
      </p>
    </div>
  )
}

export default function Booking() {
  const { user } = useAuth()
  const [date, setDate] = useState(today())
  const [party, setParty] = useState(2)
  const [slots, setSlots] = useState<Slot[] | null>(null)
  const [res, setRes] = useState<Reservation | null>(null)
  const [err, setErr] = useState('')

  async function search() {
    setErr('')
    setRes(null)
    try {
      setSlots(await api<Slot[]>(`/availability?date=${date}&party=${party}`))
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  async function book(start: string) {
    setErr('')
    try {
      setRes(await api<Reservation>('/reservations', { body: { party_size: party, start_at: start } }))
      setSlots(null)
    } catch (e) {
      setErr((e as Error).message)
      search()
    }
  }

  return (
    <>
      <h1>Đặt bàn</h1>
      <div className="card row">
        {/* Bước 1: ngày + số người; Bước 2: chọn giờ; Bước 3: đặt cọc; Bước 4: xác nhận */}
        <label>Ngày</label>
        <input type="date" value={date} min={today()} onChange={(e) => setDate(e.target.value)} />
        <label>Số người</label>
        <input type="number" min={1} max={20} value={party} onChange={(e) => setParty(+e.target.value)} style={{ width: 80 }} />
        <button onClick={search}>Tìm bàn trống</button>
      </div>
      {err && <p className="error">{err}</p>}
      {slots && (
        <div className="card slots">
          <h3>Chọn giờ</h3>
          {slots.length === 0 && <p className="muted">Không còn khung giờ nào trong ngày này.</p>}
          {slots.map((s) => (
            <button key={s.start} className={s.available ? '' : 'secondary'} disabled={!s.available || !user}
              onClick={() => book(s.start)} title={s.available ? `Còn ${s.tables_left} bàn` : 'Hết bàn'}>
              {new Date(s.start).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}
            </button>
          ))}
          {!user && <p className="muted"><Link to="/login" state={{ from: '/' }}>Đăng nhập</Link> để đặt bàn.</p>}
        </div>
      )}
      {res && (
        <div className="card">
          <h3>Đặt bàn #{res.id}: {fmtTime(res.start_at)}, {res.party_size} người, {res.table}</h3>
          <PaymentPanel reservation={res} onChange={setRes} />
          <p><Link to="/my">Xem đặt bàn của tôi</Link></p>
        </div>
      )}
    </>
  )
}
