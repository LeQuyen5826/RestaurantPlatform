import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, Cart, connectWs, getSession, MenuCategory, MenuItem, Rec, setSession, vnd } from '../api'

const STATUS: Record<string, string> = {
  submitted: 'Đã gửi bếp', preparing: 'Đang làm', ready: 'Sẵn sàng', served: 'Đã phục vụ',
}

/** Khách quét QR bàn: tham gia phiên, xem menu, giỏ chung, gửi món, theo dõi trạng thái. */
export default function TableOrder() {
  const { token = '' } = useParams()
  const [ready, setReady] = useState(false)
  const [err, setErr] = useState('')
  const [menu, setMenu] = useState<MenuCategory[]>([])
  const [cart, setCart] = useState<Cart | null>(null)
  const [recs, setRecs] = useState<Rec[]>([])
  const [myAllergies, setMyAllergies] = useState<string[]>([])
  const [hideAllergen, setHideAllergen] = useState(true)
  const [closed, setClosed] = useState(false)

  const loadCart = useCallback(() => api<Cart>('/session/cart', { session: true }).then(setCart).catch((e) => {
    if ((e as { status?: number }).status === 410) setClosed(true)
  }), [])
  const loadMenu = useCallback(() => api<MenuCategory[]>('/menu').then(setMenu), [])

  useEffect(() => {
    api<{ session_token: string }>('/sessions/join', { body: { table_token: token } })
      .then((r) => { setSession(r.session_token); setReady(true) })
      .catch((e) => setErr((e as Error).message))
  }, [token])

  useEffect(() => {
    if (!ready) return
    loadMenu(); loadCart()
    api<Rec[]>('/recommendations?limit=4').then(setRecs).catch(() => {})
    api<{ allergies: string[] } | null>('/me/profile').then((p) => p && setMyAllergies(p.allergies)).catch(() => {})
    const s = getSession()
    return s ? connectWs(s, (m) => {
      if (m.type === 'menu_changed') loadMenu()
      else if (m.type === 'session_closed') setClosed(true)
      else loadCart()
    }) : undefined
  }, [ready, loadCart, loadMenu])

  const unsafe = (i: MenuItem) => i.allergens.some((a) => myAllergies.includes(a))
  const add = async (i: MenuItem, recId?: number) => {
    try {
      await api('/session/cart', { session: true, body: { menu_item_id: i.id, qty: 1 } })
      if (recId) api(`/recommendations/${recId}/accept`, { method: 'POST', body: {} }).catch(() => {})
      loadCart()
    } catch (e) { setErr((e as Error).message) }
  }
  const setQty = (id: number, qty: number) => api(`/session/cart/${id}`, { session: true, method: 'PATCH', body: { qty } }).then(loadCart)
  const submit = async () => {
    try { await api('/session/submit', { session: true, method: 'POST', body: {} }); setErr(''); loadCart() }
    catch (e) { setErr((e as Error).message); loadMenu() }
  }

  if (closed) return <div className="card"><h2>Phiên bàn đã đóng</h2><p>Cảm ơn bạn đã dùng bữa!</p></div>
  if (!ready) return <div className="card">{err ? <p className="error">{err}</p> : <p>Đang kết nối bàn…</p>}</div>

  return (
    <>
      <h1>{cart?.table ?? 'Bàn'} · Gọi món</h1>
      {err && <p className="error">{err}</p>}
      {myAllergies.length > 0 && (
        <label><input type="checkbox" checked={hideAllergen} onChange={(e) => setHideAllergen(e.target.checked)} /> Ẩn món chứa dị ứng của tôi</label>
      )}

      {recs.length > 0 && (
        <div className="card">
          <h3>Gợi ý cho bạn</h3>
          <div className="grid">{recs.map((r) => (
            <div className="card" key={r.rec_id}>
              <b>{r.item.name}</b> <span className="muted">{vnd(r.item.price)}</span>
              <p className="muted">{r.reason_text}</p>
              <button onClick={() => add(r.item, r.rec_id)}>Thêm</button>
            </div>
          ))}</div>
        </div>
      )}

      {menu.map((c) => (
        <section key={c.name}>
          <h3>{c.name}</h3>
          <div className="grid">
            {c.items.filter((i) => !(hideAllergen && unsafe(i))).map((i) => (
              <div className="card" key={i.id} onMouseEnter={() => api('/interactions', { body: { menu_item_id: i.id, type: 'view' } }).catch(() => {})}>
                <b>{i.name}</b> <span className="muted">{vnd(i.price)}</span>
                <div className="row">
                  {i.spicy_level > 0 && <span className="badge">{'🌶'.repeat(i.spicy_level)}</span>}
                  {i.allergens.map((a) => <span key={a} className={`badge ${myAllergies.includes(a) ? 'warn' : ''}`}>{a}</span>)}
                </div>
                <button disabled={!i.available} onClick={() => add(i)}>{i.available ? 'Thêm vào giỏ' : 'Hết món'}</button>
              </div>
            ))}
          </div>
        </section>
      ))}

      <div className="card" style={{ position: 'sticky', bottom: 8 }}>
        <h3>Giỏ chung của bàn</h3>
        {cart?.cart.length === 0 && <p className="muted">Chưa có món nào trong giỏ.</p>}
        {cart?.cart.map((l) => (
          <div className="row" key={l.id}>
            <span style={{ flex: 1 }}>{l.name}</span>
            <button className="secondary" onClick={() => setQty(l.id, l.qty - 1)}>−</button>
            <b>{l.qty}</b>
            <button className="secondary" onClick={() => setQty(l.id, l.qty + 1)}>+</button>
          </div>
        ))}
        <button disabled={!cart?.cart.length} onClick={submit}>Gửi món cho bếp</button>
        {cart && cart.orders.length > 0 && (
          <>
            <h3>Món đã gọi · tạm tính {vnd(cart.total)}</h3>
            {cart.orders.map((o) => (
              <div className="row" key={o.id}><span style={{ flex: 1 }}>{o.qty}× {o.name}</span><span className="badge">{STATUS[o.status] ?? o.status}</span></div>
            ))}
          </>
        )}
      </div>
    </>
  )
}
