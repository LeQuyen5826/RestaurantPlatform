export type Role = 'customer' | 'manager' | 'waiter' | 'kitchen'

export interface User {
  id: number
  email: string | null
  phone: string | null
  full_name: string
  role: Role
  has_profile: boolean
  consent_personalization: boolean
}
export interface Payment {
  code: string
  amount: number
  status: string
  refund_status: string
  qr_url: string | null
}
export interface Reservation {
  id: number
  table: string | null
  table_id: number
  party_size: number
  start_at: string
  end_at: string
  status: string
  hold_until: string | null
  deposit_amount: number
  payment: Payment | null
}
export interface Slot {
  start: string
  available: boolean
  tables_left: number
}
export interface MenuItem {
  id: number
  name: string
  description: string
  price: number
  image_url: string
  tags: string[]
  allergens: string[]
  spicy_level: number
  cuisine: string
  available: boolean
}
export interface MenuCategory {
  id: number | null
  name: string
  items: MenuItem[]
}
export interface OrderLine {
  id: number
  menu_item_id: number
  name: string
  price: number
  qty: number
  note: string
  status: string
  allergens: string[]
}
export interface Cart {
  session_id: number
  table: string
  total: number
  cart: OrderLine[]
  orders: OrderLine[]
}
export interface Rec {
  rec_id: number
  level: number
  reason_code: string
  reason_text: string
  item: MenuItem
}
export interface KitchenLine extends OrderLine {
  table: string
  session_id: number
  created_at: string
  allergy_alert: string[]
}

const TOKEN = 'token'
const SESS = 'sessToken'
export const getToken = () => localStorage.getItem(TOKEN)
export const setToken = (t: string | null) => (t ? localStorage.setItem(TOKEN, t) : localStorage.removeItem(TOKEN))
export const getSession = () => sessionStorage.getItem(SESS)
export const setSession = (t: string | null) => (t ? sessionStorage.setItem(SESS, t) : sessionStorage.removeItem(SESS))

const BASE = import.meta.env.BASE_URL.replace(/\/$/, '') // '' khi chạy gốc, '/booking' dưới IIS

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

interface Opts {
  method?: string
  body?: unknown
  session?: boolean // gửi token phiên bàn (khách quét QR) qua X-Session-Token
}

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (opts.session) {
    const s = getSession()
    if (s) headers['X-Session-Token'] = s
  }
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${BASE}/api${path}`, {
    method: opts.method ?? (opts.body !== undefined ? 'POST' : 'GET'),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const d = data?.detail
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((e: { msg: string }) => e.msg).join('; ') : res.statusText
    throw new ApiError(res.status, msg)
  }
  return data as T
}

/** WebSocket tự kết nối lại. `token` = JWT người dùng hoặc token phiên bàn. Trả hàm đóng. */
export function connectWs(token: string, onMessage: (msg: { type: string; [k: string]: unknown }) => void): () => void {
  let ws: WebSocket | null = null
  let closed = false
  let retry = 500
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}${BASE}/ws?token=${encodeURIComponent(token)}`)
    ws.onopen = () => (retry = 500)
    ws.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data))
      } catch {
        /* bỏ qua */
      }
    }
    ws.onclose = () => {
      if (!closed) setTimeout(open, (retry = Math.min(retry * 2, 8000)))
    }
  }
  open()
  return () => {
    closed = true
    ws?.close()
  }
}

export const vnd = (n: number) => n.toLocaleString('vi-VN') + 'đ'
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString('vi-VN', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
