import { ReactNode } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Role } from './api'
import { useAuth } from './auth'
import Booking from './pages/Booking'
import Kitchen from './pages/Kitchen'
import Login from './pages/Login'
import Manager from './pages/Manager'
import MyReservations from './pages/MyReservations'
import Profile from './pages/Profile'
import TableOrder from './pages/TableOrder'
import Waiter from './pages/Waiter'

function Guard({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <p className="muted">Đang tải…</p>
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />
  if (!roles.includes(user.role)) return <p className="error">Bạn không có quyền truy cập trang này.</p>
  return <>{children}</>
}

const HOME: Record<Role, string> = { customer: '/', manager: '/manager', waiter: '/waiter', kitchen: '/kitchen' }

export default function App() {
  const { user, logout } = useAuth()
  const loc = useLocation()
  const isTable = loc.pathname.startsWith('/t/')
  return (
    <>
      {!isTable && (
        <nav className="nav">
          <Link to={user ? HOME[user.role] : '/'}>🍜 Đặt bàn</Link>
          {user?.role === 'customer' && (
            <>
              <Link to="/my">Đặt bàn của tôi</Link>
              <Link to="/profile">Khẩu vị & dữ liệu</Link>
            </>
          )}
          {user?.role === 'waiter' && <Link to="/waiter">Phục vụ</Link>}
          {user?.role === 'kitchen' && <Link to="/kitchen">Bếp</Link>}
          {user?.role === 'manager' && <Link to="/manager">Quản lý</Link>}
          <span className="spacer" />
          {user ? (
            <button className="link" onClick={logout}>Đăng xuất ({user.full_name || user.email || user.phone})</button>
          ) : (
            <Link to="/login">Đăng nhập</Link>
          )}
        </nav>
      )}
      <main className="container">
        <Routes>
          <Route path="/" element={user && user.role !== 'customer' ? <Navigate to={HOME[user.role]} replace /> : <Booking />} />
          <Route path="/login" element={<Login />} />
          <Route path="/my" element={<Guard roles={['customer']}><MyReservations /></Guard>} />
          <Route path="/profile" element={<Guard roles={['customer']}><Profile /></Guard>} />
          <Route path="/t/:token" element={<TableOrder />} />
          <Route path="/waiter" element={<Guard roles={['waiter', 'manager']}><Waiter /></Guard>} />
          <Route path="/kitchen" element={<Guard roles={['kitchen', 'manager', 'waiter']}><Kitchen /></Guard>} />
          <Route path="/manager" element={<Guard roles={['manager']}><Manager /></Guard>} />
          <Route path="*" element={<p>Không tìm thấy trang.</p>} />
        </Routes>
      </main>
    </>
  )
}
