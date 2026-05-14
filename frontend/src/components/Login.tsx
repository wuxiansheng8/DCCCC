import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!username.trim() || !password.trim()) {
      setError('请输入用户名和密码');
      return;
    }

    try {
      const res = await api.login(username.trim(), password);
      localStorage.setItem('token', res.access_token);
      navigate('/');
    } catch (err: any) {
      setError(err.message === 'Incorrect username or password' ? '用户名或密码错误' : err.message || '连接失败，请检查后端服务');
    }
  };

  return (
    <div className="login-container">
      <div className="login-box">
        <h2 style={{ marginBottom: '24px', textAlign: 'center' }}>监控系统登录</h2>
        <form onSubmit={handleLogin}>
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>用户名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoFocus
            />
          </div>
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
            />
          </div>
          {error && <p style={{ color: 'var(--error)', marginBottom: '16px', fontSize: '0.875rem' }}>{error}</p>}
          <button type="submit" className="btn-primary">立即登录</button>
        </form>
      </div>
    </div>
  );
};

export default Login;
