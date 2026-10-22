import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken, User } from './api'

interface AuthCtx {
  user: User | null
  loading: boolean
  login: (identifier: string, password: string) => Promise<User>
  register: (identifier: string, password: string, fullName: string) => Promise<User>
  logout: () => void
  refresh: () => Promise<void>
}
const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      return
    }
    try {
      setUser(await api<User>('/me'))
    } catch {
      setToken(null)
      setUser(null)
    }
  }, [])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  const finish = (r: { access_token: string; user: User }) => {
    setToken(r.access_token)
    setUser(r.user)
    return r.user
  }
  const login: AuthCtx['login'] = async (identifier, password) =>
    finish(await api('/auth/login', { body: { identifier, password } }))
  const register: AuthCtx['register'] = async (identifier, password, fullName) => {
    const contact = identifier.includes('@') ? { email: identifier } : { phone: identifier }
    return finish(await api('/auth/register', { body: { ...contact, password, full_name: fullName } }))
  }
  const logout = () => {
    setToken(null)
    setUser(null)
  }
  return <Ctx.Provider value={{ user, loading, login, register, logout, refresh }}>{children}</Ctx.Provider>
}
