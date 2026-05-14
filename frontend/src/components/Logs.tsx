import { useEffect, useState } from 'react';
import { Activity, Clock3, RefreshCw, Repeat2, WifiOff } from 'lucide-react';
import { api } from '../api';
import { formatDurationSeconds, formatShanghaiTime, translateLogLevel, translateSystemLog } from '../utils/format';

type LogItem = {
  id: number;
  level: string;
  message: string;
  created_at: string;
};

type RuntimeHour = {
  hour_start: string;
  hour_end: string;
  status: 'stable' | 'partial' | 'interrupted' | 'down';
  interruption_count: number;
};

type SystemStatus = {
  is_running: boolean;
  worker_running: boolean;
  stable_uptime_started_at?: string;
  stable_uptime_seconds: number;
  runtime_hours: RuntimeHour[];
  downtime_count_24h: number;
  downtime_seconds_24h: number;
  token_switch_count_24h: number;
};

const runtimeStatusLabel: Record<RuntimeHour['status'], string> = {
  stable: '稳定',
  partial: '部分运行',
  interrupted: '断开',
  down: '离线',
};

const formatHourLabel = (value: string) => {
  const date = new Date(value.includes('T') ? `${value.replace(/Z$/, '')}Z` : `${value.replace(' ', 'T')}Z`);
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
};

const formatRangeLabel = (hours: RuntimeHour[]) => {
  if (hours.length === 0) {
    return '暂无数据';
  }
  return `${formatHourLabel(hours[0].hour_start)} - ${formatHourLabel(hours[hours.length - 1].hour_end)}`;
};

const Logs = () => {
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 1000);
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      const [logsRes, statusRes] = await Promise.all([
        api.get('/logs?limit=300'),
        api.get('/system/status'),
      ]);
      setLogs(logsRes);
      setStatus(statusRes);
      setError('');
    } catch (err: any) {
      setError(err.message || '读取日志失败');
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>系统运行日志</h2>
          <p className="muted" style={{ marginTop: '6px' }}>保留最近 1 天日志，并按小时标记最近 24 小时运行状态</p>
        </div>
        <button onClick={fetchData} className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '8px', width: 'auto' }}>
          <RefreshCw size={18} /> 刷新日志
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="runtime-summary">
        <div className="card runtime-card">
          <div className="runtime-card-title">
            <Clock3 size={20} />
            <span>稳定运行时间</span>
          </div>
          <strong>{formatDurationSeconds(status?.stable_uptime_seconds || 0)}</strong>
          <p className="muted">
            {status?.stable_uptime_started_at
              ? `本轮开始：${formatShanghaiTime(status.stable_uptime_started_at)}`
              : '当前未处于稳定运行状态'}
          </p>
        </div>

        <div className="card runtime-card">
          <div className="runtime-card-title">
            <WifiOff size={20} />
            <span>24 小时断开</span>
          </div>
          <strong>{status?.downtime_count_24h || 0} 次</strong>
          <p className="muted">累计 {formatDurationSeconds(status?.downtime_seconds_24h || 0)}</p>
        </div>

        <div className="card runtime-card">
          <div className="runtime-card-title">
            <Repeat2 size={20} />
            <span>24 小时 Token 切换</span>
          </div>
          <strong>{status?.token_switch_count_24h || 0} 次</strong>
          <p className="muted">{status?.is_running && status?.worker_running ? '监控线程运行中' : '监控线程未运行'}</p>
        </div>
      </div>

      <div className="card">
        <div className="timeline-header">
          <h3 className="card-title"><Activity size={20} /> 24 小时可用性</h3>
          <span className="muted">{formatRangeLabel(status?.runtime_hours || [])}</span>
        </div>
        <div className="runtime-timeline">
          {(status?.runtime_hours || []).map((hour) => (
            <div
              key={hour.hour_start}
              className={`runtime-segment runtime-${hour.status}`}
              title={`${formatShanghaiTime(hour.hour_start)} - ${formatShanghaiTime(hour.hour_end)}：${runtimeStatusLabel[hour.status]}${hour.interruption_count ? `，断开 ${hour.interruption_count} 次` : ''}`}
            />
          ))}
        </div>
        <div className="timeline-scale">
          {(status?.runtime_hours || []).filter((_, index) => index % 4 === 0).map((hour) => (
            <span key={hour.hour_start}>{formatHourLabel(hour.hour_start)}</span>
          ))}
        </div>
        <div className="runtime-legend">
          <span><i className="runtime-dot runtime-stable" />稳定</span>
          <span><i className="runtime-dot runtime-interrupted" />断开后恢复</span>
          <span><i className="runtime-dot runtime-down" />离线</span>
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th style={{ width: '200px' }}>时间</th>
              <th style={{ width: '100px' }}>级别</th>
              <th>内容</th>
            </tr>
          </thead>
          <tbody>
            {logs.map(log => (
              <tr key={log.id}>
                <td className="muted" style={{ fontSize: '0.875rem' }}>
                  {formatShanghaiTime(log.created_at)}
                </td>
                <td>
                  <span className={`text-${log.level}`}>
                    {translateLogLevel(log.level)}
                  </span>
                </td>
                <td style={{ fontSize: '0.875rem' }}>{translateSystemLog(log.message)}</td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={3} className="empty">暂无日志记录</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default Logs;
