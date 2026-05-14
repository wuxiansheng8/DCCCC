import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { LayoutDashboard, UserRound, Server, Settings, ScrollText, LogOut } from 'lucide-react';

const DashboardLayout = () => {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <div className="app-container">
      <aside className="sidebar">
        <div style={{ padding: '0 24px 32px', borderBottom: '1px solid var(--border)' }}>
          <h1 style={{ fontSize: '1.25rem', color: 'var(--primary)' }}>DC 转发监控</h1>
        </div>

        <nav style={{ flex: 1, paddingTop: '24px' }}>
          <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`} end>
            <LayoutDashboard size={20} /> 系统概览
          </NavLink>
          <NavLink to="/tokens" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <UserRound size={20} /> DC 账号
          </NavLink>
          <NavLink to="/targets" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <Server size={20} /> 监控目标
          </NavLink>
          <NavLink to="/logs" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <ScrollText size={20} /> 运行日志
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <Settings size={20} /> 系统设置
          </NavLink>
        </nav>

        <div style={{ padding: '24px' }}>
          <button onClick={handleLogout} className="nav-item" style={{ width: '100%', background: 'transparent', border: 'none', cursor: 'pointer' }}>
            <LogOut size={20} /> 退出登录
          </button>
        </div>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
};

export default DashboardLayout;
