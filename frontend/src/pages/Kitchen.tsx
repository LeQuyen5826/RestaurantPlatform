import { useCallback, useEffect, useState } from 'react'
import { api, connectWs, getToken, KitchenLine, MenuCategory } from '../api'
import { useAuth } from '../auth'

export default function Kitchen() {
  const { user } = useAuth()
  const [lines, setLines] = useState<KitchenLine[]>([])
  const [menu, setMenu] = useState<MenuCategory[]>([])
  const [err, setErr] = useState('')
  const load = useCallback(() => api<KitchenLine[]>('/kitchen/orders').then(setLines), [])
  const loadMenu = useCallback(() => api<MenuCategory[]>('/menu').then(setMenu), [])

  useEffect(() => {
    load(); loadMenu()
    return connectWs(getToken()!, (m) => (m.type === 'menu_changed' ? loadMenu() : load()))
  }, [load, loadMenu])

  const canCook = user?.role === 'kitchen'
  const move = async (l: KitchenLine, status: 'preparing' | 'ready') => {
    try { await api(`/order-items/${l.id}/status`, { method: 'PATCH', body: { status } }); load() }
    catch (e) { setErr((e as Error).message) }
  }
  const col = (title: string, status: string, next?: 'preparing' | 'ready') => (
    <div>
      <h3>{title} ({lines.filter((l) => l.status === status).length})</h3>
      {lines.filter((l) => l.status === status).map((l) => {
        const warn = l.allergy_alert.length > 0 || /dị ứng|di ung|allerg/i.test(l.note)
        return (
          <div key={l.id} className={`card ${warn ? 'alert' : ''}`}>
            <b>{l.table}</b> · {l.qty}× {l.name}
            {l.note && <p className={warn ? 'error' : 'muted'}><b>Ghi chú: {l.note}</b></p>}
            {l.allergy_alert.length > 0 && <p><span className="badge warn">⚠ Khách dị ứng: {l.allergy_alert.join(", ")}</span></p>}
            <div className="row">{l.allergens.map((a) => <span key={a} className="badge">{a}</span>)}</div>
            {next && canCook && <button onClick={() => move(l, next)}>{next === 'preparing' ? 'Bắt đầu làm' : 'Xong'}</button>}
          </div>
        )
      })}
    </div>
  )

  return (
    <div className="kitchen">
      <h1>Màn hình bếp</h1>
      {err && <p className="error">{err}</p>}
      <div className="cols">
        {col('Mới', 'submitted', 'preparing')}
        {col('Đang làm', 'preparing', 'ready')}
        {col('Chờ bưng', 'ready')}
      </div>
      {canCook && (
        <div className="card">
          <h3>Đánh dấu hết món</h3>
          <div className="row">{menu.flatMap((c) => c.items).map((i) => (
            <button key={i.id} className={i.available ? 'secondary' : ''}
              onClick={() => api(`/menu/items/${i.id}/availability`, { method: 'PATCH', body: { available: !i.available } }).then(loadMenu)}>
              {i.available ? i.name : `${i.name} (hết)`}
            </button>
          ))}</div>
        </div>
      )}
    </div>
  )
}
