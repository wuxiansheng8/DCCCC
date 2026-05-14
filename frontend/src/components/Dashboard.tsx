import { useEffect, useState } from 'react';
import { Activity, AlertTriangle, Play, RefreshCw, Square } from 'lucide-react';
import { api } from '../api';
import { formatShanghaiTime, translateLogLevel, translateSystemLog } from '../utils/format';

type Token = {
  id: number;
  note?: string;
  status: string;
  last_used?: string;
  next_retry_at?: string;
  error_message?: string;
};

type LogItem = {
  id: number;
  level: string;
  message: string;
  created_at: string;
};

type SystemStatus = {
  is_running: boolean;
  worker_running: boolean;
  active_token_id?: number;
  active_token_status?: string;
  last_started_at?: string;
  last_stopped_at?: string;
  last_heartbeat_at?: string;
  last_forwarded_at?: string;
  last_error?: string;
  token_total: number;
  token_online: number;
  token_available: number;
  token_disabled: number;
  token_invalid: number;
  token_retrying: number;
  token_health_worker_running: boolean;
};

const formatTime = formatShanghaiTime;

const Dashboard = () => {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [tokens, setTokens] = useState<Token[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      const [statusRes, tokensRes, logsRes] = await Promise.all([
        api.get('/system/status'),
        api.get('/tokens'),
        api.get('/logs?limit=10')
      ]);

      setStatus(statusRes);
      setTokens(tokensRes);
      setLogs(logsRes);
      setError('');
    } catch (err: any) {
      setError(err.message || '连接失败，请检查后端服务是否正常运行');
    }
  };

  const toggleSystem = async () => {
    setLoading(true);
    setError('');
    try {
      if (status?.is_running) {
        await api.post('/system/stop');
      } else {
        await api.post('/system/start');
      }
      await fetchData();
    } catch (err: any) {
      setError(err.message || '操作失败');
    } finally {
      setLoading(false);
    }
  };

  const activeToken = status?.active_token_id
    ? tokens.find((token) => token.id === status.active_token_id)
    : tokens.find((token) => token.status === 'online');

  return (
    <div>
      <div className="page-header">
        <h2>系统概览</h2>
        <button
          onClick={toggleSystem}
          className={status?.is_running ? 'btn-danger' : 'btn-primary'}
          disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 24px', width: 'auto' }}
        >
          {status?.is_running ? <><Square size={18} /> 停止监控</> : <><Play size={18} /> 开始监控</>}
        </button>
      </div>

      {error && (
        <div className="alert alert-error">
          <AlertTriangle size={18} /> {error}
        </div>
      )}

      <div className="metric-grid">
        <div className="card">
          <p className="muted">监控系统状态</p>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
            <div className={`status-dot ${status?.is_running ? 'online' : 'offline'}`}></div>
            <span style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>{status?.is_running ? '运行中' : '已停止'}</span>
          </div>
          <p className="muted" style={{ marginTop: '8px' }}>监听线程：{status?.worker_running ? '运行中' : '未运行'}</p>
          <p className="muted" style={{ marginTop: '4px' }}>巡检线程：{status?.token_health_worker_running ? '运行中' : '未运行'}</p>
        </div>
        <div className="card">
          <p className="muted">账号状态</p>
          <span style={{ display: 'block', fontSize: '1.5rem', fontWeight: 'bold', marginTop: '8px' }}>
            {status?.token_online ?? 0} / {status?.token_total ?? 0}
          </span>
          <p className="muted" style={{ marginTop: '8px' }}>
            可用 {status?.token_available ?? 0}，重试中 {status?.token_retrying ?? 0}
          </p>
        </div>
        <div className="card">
          <p className="muted">最近转发</p>
          <span style={{ display: 'block', fontSize: '1rem', fontWeight: 'bold', marginTop: '8px' }}>
            {formatTime(status?.last_forwarded_at)}
          </span>
          <p className="muted" style={{ marginTop: '8px' }}>日志保留最近 1 天</p>
        </div>
      </div>

      <div className="content-grid">
        <div className="card">
          <h3 className="card-title"><Activity size={20} /> 最近动态</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {logs.map(log => (
              <div key={log.id} className="log-row">
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', marginBottom: '4px' }}>
                  <span className={`text-${log.level}`}>[{translateLogLevel(log.level)}]</span>
                  <span className="muted">{formatTime(log.created_at)}</span>
                </div>
                <p>{translateSystemLog(log.message)}</p>
              </div>
            ))}
            {logs.length === 0 && <p className="empty">暂无日志信息</p>}
          </div>
        </div>

        <div className="card">
          <h3 className="card-title">当前执行账号</h3>
          {activeToken ? (
            <div>
              <div className={`badge badge-${activeToken.status}`} style={{ marginBottom: '16px', display: 'inline-block' }}>
                {activeToken.status}
              </div>
              <p style={{ fontSize: '0.875rem', wordBreak: 'break-all', lineHeight: 1.8 }}>
                <strong>账号 ID:</strong> {activeToken.id}<br />
                <strong>备注:</strong> {activeToken.note || '未备注'}<br />
                <strong>最后活动:</strong> {formatTime(activeToken.last_used)}<br />
                <strong>下次重试:</strong> {formatTime(activeToken.next_retry_at)}
              </p>
            </div>
          ) : (
            <p className="muted">当前没有在线监控账号</p>
          )}

          {status?.last_error && (
            <div className="alert alert-error" style={{ marginTop: '20px' }}>
              <AlertTriangle size={18} /> {status.last_error}
            </div>
          )}

          <button onClick={fetchData} className="btn-secondary" style={{ marginTop: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <RefreshCw size={16} /> 刷新状态
          </button>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
