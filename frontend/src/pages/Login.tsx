import { FormEvent, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

const HOME = { customer: '/', manager: '/manager', waiter: '/waiter', kitchen: '/kitchen' } as const

export default function Login() {
  const { login, register } = useAuth()
  const nav = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [err, setErr] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      const u = mode === 'login' ? await login(identifier, password) : await register(identifier, password, name)
      nav(from ?? HOME[u.role], { replace: true })
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  return (
    <form className="card" onSubmit={submit} style={{ maxWidth: 420, margin: '24px auto' }}>
      <h2>{mode === 'login' ? 'Đăng nhập' : 'Tạo tài khoản khách'}</h2>
      {mode === 'register' && (
        <>
          <label>Họ tên</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </>
      )}
      <label>Email hoặc số điện thoại</label>
      <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} required />
      <label>Mật khẩu (tối thiểu 8 ký tự)</label>
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
      {err && <p className="error">{err}</p>}
      <div className="row" style={{ marginTop: 12 }}>
        <button type="submit">{mode === 'login' ? 'Đăng nhập' : 'Đăng ký'}</button>
        <button type="button" className="link" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
          {mode === 'login' ? 'Chưa có tài khoản?' : 'Đã có tài khoản'}
        </button>
      </div>
    </form>
  )
}
