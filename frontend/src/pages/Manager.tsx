import { QRCodeSVG } from 'qrcode.react'
import { FormEvent, useCallback, useEffect, useState } from 'react'
import { api, MenuCategory, vnd } from '../api'

type Tab = 'dash' | 'menu' | 'tables' | 'payments' | 'staff'
interface Dash {
  reservations: { total: number; by_status: Record<string, number> }
  no_show_rate: number; deposit_collected: number
  top_items: { name: string; qty: number }[]
  recommendation: { shown: number; accepted: number; acceptance_rate: number }
}
interface TableRow { id: number; name: string; area: string; capacity: number }
interface QueueRow { id: number; transaction_id: string; amount: number; result: string; content: string | null }
interface RefundRow { id: number; reservation_id: number; amount: number; refund_status: string }
interface StaffRow { id: number; email: string; role: string; is_active: boolean }

export default function Manager() {
  const [tab, setTab] = useState<Tab>('dash')
  const names: Record<Tab, string> = { dash: 'Tổng quan', menu: 'Thực đơn', tables: 'Bàn & QR', payments: 'Đối soát cọc', staff: 'Nhân sự' }
  return (
    <>
      <h1>Quản lý</h1>
      <div className="tabs">{(Object.keys(names) as Tab[]).map((t) => (
        <button key={t} className={tab === t ? '' : 'secondary'} onClick={() => setTab(t)}>{names[t]}</button>
      ))}</div>
      {tab === 'dash' && <Dashboard />}
      {tab === 'menu' && <MenuAdmin />}
      {tab === 'tables' && <Tables />}
      {tab === 'payments' && <Payments />}
      {tab === 'staff' && <Staff />}
    </>
  )
}

function Dashboard() {
  const [d, setD] = useState<Dash | null>(null)
  useEffect(() => { api<Dash>('/dashboard').then(setD) }, [])
  if (!d) return <p className="muted">Đang tải…</p>
  return (
    <div className="grid">
      <div className="card"><h3>Đặt bàn (30 ngày)</h3><b>{d.reservations.total}</b>
        <p className="muted">{Object.entries(d.reservations.by_status).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p></div>
      <div className="card"><h3>Tỷ lệ no-show</h3><b>{(d.no_show_rate * 100).toFixed(1)}%</b></div>
      <div className="card"><h3>Tiền cọc thu</h3><b>{vnd(d.deposit_collected)}</b></div>
      <div className="card"><h3>Món bán chạy</h3>{d.top_items.map((t) => <div key={t.name}>{t.name}: {t.qty}</div>)}</div>
      <div className="card"><h3>Gợi ý được chấp nhận</h3><b>{(d.recommendation.acceptance_rate * 100).toFixed(1)}%</b>
        <p className="muted">{d.recommendation.accepted}/{d.recommendation.shown} lượt hiển thị</p></div>
    </div>
  )
}

function MenuAdmin() {
  const [menu, setMenu] = useState<MenuCategory[]>([])
  const [f, setF] = useState({ name: '', price: 50000, category_id: '', tags: '', allergens: '', spicy_level: 0, cuisine: 'viet' })
  const load = useCallback(() => api<MenuCategory[]>('/menu').then(setMenu), [])
  useEffect(() => { load() }, [load])
  async function add(e: FormEvent) {
    e.preventDefault()
    const split = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
    await api('/menu/items', { body: { ...f, category_id: f.category_id ? +f.category_id : null, tags: split(f.tags), allergens: split(f.allergens) } })
    setF({ ...f, name: '' }); load()
  }
  return (
    <>
      <form className="card row" onSubmit={add}>
        <input placeholder="Tên món" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        <input type="number" value={f.price} step={5000} onChange={(e) => setF({ ...f, price: +e.target.value })} style={{ width: 110 }} />
        <select value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}>
          <option value="">Danh mục…</option>{menu.filter((c) => c.id).map((c) => <option key={c.id} value={c.id!}>{c.name}</option>)}
        </select>
        <input placeholder="tags: nuoc, bo" value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} />
        <input placeholder="dị ứng: peanut, egg" value={f.allergens} onChange={(e) => setF({ ...f, allergens: e.target.value })} />
        <select value={f.spicy_level} onChange={(e) => setF({ ...f, spicy_level: +e.target.value })}>{[0, 1, 2, 3].map((n) => <option key={n} value={n}>Cay {n}</option>)}</select>
        <button>Thêm món</button>
      </form>
      {menu.map((c) => (
        <div className="card" key={c.name}>
          <h3>{c.name}</h3>
          <table><tbody>{c.items.map((i) => (
            <tr key={i.id}>
              <td>{i.name}</td><td>{vnd(i.price)}</td><td className="muted">{i.tags.join(', ')} | {i.allergens.join(', ')}</td>
              <td><button className="secondary" onClick={() => api(`/menu/items/${i.id}/availability`, { method: 'PATCH', body: { available: !i.available } }).then(load)}>{i.available ? 'Đang bán' : 'Hết món'}</button></td>
              <td><button className="secondary" onClick={() => confirm('Xóa món?') && api(`/menu/items/${i.id}`, { method: 'DELETE' }).then(load)}>Xóa</button></td>
            </tr>
          ))}</tbody></table>
        </div>
      ))}
    </>
  )
}

function Tables() {
  const [rows, setRows] = useState<TableRow[]>([])
  const [qr, setQr] = useState<{ table: string; url: string } | null>(null)
  useEffect(() => { api<TableRow[]>('/tables').then(setRows) }, [])
  return (
    <>
      <div className="card"><table><tbody>{rows.map((t) => (
        <tr key={t.id}><td>{t.name}</td><td>{t.area}</td><td>{t.capacity} chỗ</td>
          <td><button className="secondary" onClick={async () => setQr(await api(`/tables/${t.id}/qr`))}>Xem QR</button></td></tr>
      ))}</tbody></table></div>
      {qr && (
        <div className="card">
          <h3>{qr.table}: in mã này dán tại bàn</h3>
          <QRCodeSVG value={qr.url} size={220} />
          <p className="muted" style={{ wordBreak: 'break-all' }}>{qr.url}</p>
          <button onClick={() => window.print()}>In</button>
        </div>
      )}
    </>
  )
}

function Payments() {
  const [queue, setQueue] = useState<QueueRow[]>([])
  const [refunds, setRefunds] = useState<RefundRow[]>([])
  const load = useCallback(async () => {
    setQueue(await api<QueueRow[]>('/payments/queue')); setRefunds(await api<RefundRow[]>('/payments/refunds'))
  }, [])
  useEffect(() => { load() }, [load])
  return (
    <>
      <div className="card">
        <h3>Giao dịch chưa khớp</h3>
        {queue.length === 0 && <p className="muted">Không có.</p>}
        {queue.map((q) => (
          <div className="row" key={q.id}>
            <span style={{ flex: 1 }}>#{q.transaction_id} · {vnd(q.amount)} · <span className="badge">{q.result}</span> · {q.content}</span>
            <button className="secondary" onClick={() => api(`/payments/queue/${q.id}/resolve`, { body: { note: prompt('Ghi chú xử lý') ?? '' } }).then(load)}>Đã xử lý</button>
          </div>
        ))}
      </div>
      <div className="card">
        <h3>Hoàn cọc (chuyển khoản thủ công, hệ thống chỉ ghi vết)</h3>
        {refunds.map((r) => (
          <div className="row" key={r.id}>
            <span style={{ flex: 1 }}>Đặt bàn #{r.reservation_id} · {vnd(r.amount)} · <span className="badge">{r.refund_status}</span></span>
            {r.refund_status === 'refund_pending' && (
              <button onClick={() => api(`/payments/${r.id}/refund-recorded`, { body: { note: prompt('Mã giao dịch hoàn') ?? '' } }).then(load)}>Đã hoàn</button>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

function Staff() {
  const [rows, setRows] = useState<StaffRow[]>([])
  const [f, setF] = useState({ email: '', password: '', role: 'waiter', full_name: '' })
  const load = useCallback(() => api<StaffRow[]>('/staff').then(setRows), [])
  useEffect(() => { load() }, [load])
  async function add(e: FormEvent) { e.preventDefault(); await api('/staff', { body: f }); setF({ ...f, email: '', password: '' }); load() }
  return (
    <>
      <form className="card row" onSubmit={add}>
        <input placeholder="Email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required />
        <input placeholder="Mật khẩu" type="password" minLength={8} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
        <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="waiter">Phục vụ</option><option value="kitchen">Bếp</option></select>
        <button>Tạo tài khoản</button>
      </form>
      <div className="card"><table><tbody>{rows.map((s) => (
        <tr key={s.id}><td>{s.email}</td><td>{s.role}</td>
          <td><button className="secondary" onClick={() => api(`/staff/${s.id}`, { method: 'PATCH', body: { is_active: !s.is_active } }).then(load)}>{s.is_active ? 'Khóa' : 'Mở khóa'}</button></td></tr>
      ))}</tbody></table></div>
    </>
  )
}
