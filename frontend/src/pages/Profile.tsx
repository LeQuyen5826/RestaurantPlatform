import { FormEvent, useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'

const ALLERGENS = ['peanut', 'treenut', 'shellfish', 'fish', 'egg', 'milk', 'soy', 'gluten']
const CUISINES = ['viet', 'han', 'nhat', 'thai', 'au']

interface P { spicy_level: number; diet: string; allergies: string[]; cuisines: string[]; budget_max: number; consent_personalization: boolean }

export default function Profile() {
  const { refresh } = useAuth()
  const [p, setP] = useState<P>({ spicy_level: 1, diet: 'none', allergies: [], cuisines: [], budget_max: 0, consent_personalization: false })
  const [msg, setMsg] = useState('')
  useEffect(() => { api<P | null>('/me/profile').then((d) => d && setP(d)) }, [])

  const toggle = (k: 'allergies' | 'cuisines', v: string) =>
    setP((s) => ({ ...s, [k]: s[k].includes(v) ? s[k].filter((x) => x !== v) : [...s[k], v] }))

  async function save(e: FormEvent) {
    e.preventDefault()
    await api('/me/profile', { method: 'PUT', body: p })
    await api('/me/consent', { method: 'PUT', body: { personalization: p.consent_personalization } })
    await refresh()
    setMsg('Đã lưu.')
  }

  async function exportData() {
    const data = await api('/me/export')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    a.download = 'du-lieu-ca-nhan.json'
    a.click()
  }

  async function wipe() {
    if (!confirm('Xóa dữ liệu cá nhân và vô hiệu hóa tài khoản? Không thể hoàn tác.')) return
    await api('/me', { method: 'DELETE' })
    localStorage.removeItem('token')
    location.href = import.meta.env.BASE_URL
  }

  return (
    <form onSubmit={save}>
      <h1>Khẩu vị & dữ liệu cá nhân</h1>
      <div className="card">
        <label>1. Mức cay: {['Không cay', 'Cay nhẹ', 'Cay vừa', 'Rất cay'][p.spicy_level]}</label>
        <input type="range" min={0} max={3} value={p.spicy_level} onChange={(e) => setP({ ...p, spicy_level: +e.target.value })} />
        <label>2. Chế độ ăn</label>
        <select value={p.diet} onChange={(e) => setP({ ...p, diet: e.target.value })}>
          <option value="none">Ăn bình thường</option><option value="vegetarian">Ăn chay (có trứng/sữa)</option><option value="vegan">Thuần chay</option>
        </select>
        <label>3. Dị ứng (món chứa các thành phần này sẽ bị loại khỏi gợi ý)</label>
        <div className="row">{ALLERGENS.map((a) => (
          <label key={a}><input type="checkbox" checked={p.allergies.includes(a)} onChange={() => toggle('allergies', a)} /> {a}</label>
        ))}</div>
        <label>4. Ẩm thực yêu thích</label>
        <div className="row">{CUISINES.map((c) => (
          <label key={c}><input type="checkbox" checked={p.cuisines.includes(c)} onChange={() => toggle('cuisines', c)} /> {c}</label>
        ))}</div>
        <label>5. Ngân sách tối đa mỗi món (0 = không giới hạn)</label>
        <input type="number" min={0} step={10000} value={p.budget_max} onChange={(e) => setP({ ...p, budget_max: +e.target.value })} />
      </div>
      <div className="card">
        <label>
          <input type="checkbox" checked={p.consent_personalization} onChange={(e) => setP({ ...p, consent_personalization: e.target.checked })} />{' '}
          Tôi đồng ý cho nhà hàng dùng lịch sử gọi món và khẩu vị của tôi để cá nhân hóa gợi ý (có thể rút lại bất cứ lúc nào;
          khi rút, lịch sử gọi món đã ghi sẽ bị xóa).
        </label>
        <p className="muted">Thông tin dị ứng được mã hóa khi lưu.</p>
      </div>
      <div className="row"><button type="submit">Lưu</button>
        <button type="button" className="secondary" onClick={exportData}>Xuất dữ liệu</button>
        <button type="button" className="secondary" onClick={wipe}>Xóa dữ liệu của tôi</button></div>
      {msg && <p className="ok">{msg}</p>}
    </form>
  )
}
