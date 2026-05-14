import { useEffect, useState } from 'react';
import { Ban, Check, Key, Pencil, Plus, RotateCcw, SearchCheck, Server, Tag, Trash2, X } from 'lucide-react';
import { api } from '../api';
import { formatShanghaiTime } from '../utils/format';

type Token = {
  id: number;
  token: string;
  note?: string;
  status: string;
  last_used?: string;
  next_retry_at?: string;
  last_checked_at?: string;
  next_check_at?: string;
  failure_count: number;
  error_message?: string;
};

const statusLabel: Record<string, string> = {
  online: '在线',
  standby: '待命',
  offline: '离线',
  invalid: '无效',
  rate_limited: '限流重试',
  disabled: '已禁用'
};

const formatTime = formatShanghaiTime;

const tokenCheckMessage = (token: Token) => {
  if (token.error_message) {
    return `Token 检测通过，但有提醒：${token.error_message}`;
  }
  return token.status === 'standby' ? 'Token 检测通过' : `Token 检测完成：${statusLabel[token.status] || token.status}`;
};

const serverCheckMessage = (token: Token) => {
  if (token.error_message) {
    return `服务器覆盖检查有提醒：${token.error_message}`;
  }
  return '服务器覆盖检查通过';
};

const Tokens = () => {
  const [tokens, setTokens] = useState<Token[]>([]);
  const [newToken, setNewToken] = useState('');
  const [newNote, setNewNote] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingNote, setEditingNote] = useState('');
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetchTokens();
  }, []);

  const fetchTokens = async () => {
    try {
      const data = await api.get('/tokens');
      setTokens(data);
      setSelectedIds((current) => current.filter((id) => data.some((token: Token) => token.id === id)));
      setError('');
    } catch (err: any) {
      setError(err.message || '读取账号列表失败');
    }
  };

  const selectableTokens = tokens.filter((token) => token.status !== 'online');
  const allSelected = selectableTokens.length > 0 && selectableTokens.every((token) => selectedIds.includes(token.id));

  const toggleSelected = (id: number) => {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };

  const toggleSelectAll = () => {
    setSelectedIds(allSelected ? [] : selectableTokens.map((token) => token.id));
  };

  const validateToken = () => {
    const value = newToken.trim();
    if (value.length < 20) return 'Token 长度看起来不正确';
    if (/\s/.test(value)) return 'Token 不能包含空格或换行';
    if (newNote.trim().length > 100) return '备注不能超过 100 个字符';
    return '';
  };

  const addToken = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = validateToken();
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      const res = await api.post('/tokens', { token: newToken.trim(), note: newNote.trim() || undefined });
      setNewToken('');
      setNewNote('');
      setMessage(res.error_message ? `账号已添加，但有提醒：${res.error_message}` : '账号已添加，Token 检测通过');
      await fetchTokens();
    } catch (err: any) {
      await fetchTokens();
      setError(err.message || '添加账号失败');
    }
  };

  const startEditNote = (token: Token) => {
    setEditingId(token.id);
    setEditingNote(token.note || '');
    setError('');
    setMessage('');
  };

  const saveNote = async (id: number) => {
    if (editingNote.trim().length > 100) {
      setError('备注不能超过 100 个字符');
      return;
    }

    try {
      await api.patch(`/tokens/${id}`, { note: editingNote.trim() || null });
      setEditingId(null);
      setEditingNote('');
      setMessage('备注已更新');
      await fetchTokens();
    } catch (err: any) {
      setError(err.message || '更新备注失败');
    }
  };

  const updateStatus = async (id: number, status: 'standby' | 'disabled') => {
    try {
      await api.patch(`/tokens/${id}/status`, { status });
      setMessage(status === 'disabled' ? '账号已禁用' : '账号已恢复待命');
      await fetchTokens();
    } catch (err: any) {
      setError(err.message || '更新账号状态失败');
    }
  };

  const checkToken = async (id: number) => {
    setCheckingId(id);
    setError('');
    setMessage('');
    try {
      const res = await api.post(`/tokens/${id}/check`);
      setMessage(tokenCheckMessage(res));
      await fetchTokens();
    } catch (err: any) {
      setError(err.message || '检测 Token 失败');
    } finally {
      setCheckingId(null);
    }
  };

  const checkTokenServers = async (id: number) => {
    setCheckingId(id);
    setError('');
    setMessage('');
    try {
      const res = await api.post(`/tokens/${id}/check-servers`);
      setMessage(serverCheckMessage(res));
      await fetchTokens();
    } catch (err: any) {
      setError(err.message || '检查服务器覆盖失败');
    } finally {
      setCheckingId(null);
    }
  };

  const deleteToken = async (id: number) => {
    if (!confirm('确定要删除这个账号吗？')) return;
    try {
      await api.delete(`/tokens/${id}`);
      setMessage('账号已删除');
      await fetchTokens();
    } catch (err: any) {
      setError(err.message || '删除账号失败');
    }
  };

  const bulkDeleteTokens = async () => {
    if (selectedIds.length === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedIds.length} 个账号吗？`)) return;

    try {
      const res = await api.post('/tokens/bulk-delete', { ids: selectedIds });
      setSelectedIds([]);
      setMessage(res.skipped_ids?.length
        ? `已删除 ${res.deleted_ids.length} 个账号，跳过 ${res.skipped_ids.length} 个在线账号`
        : `已删除 ${res.deleted_ids.length} 个账号`);
      await fetchTokens();
    } catch (err: any) {
      setError(err.message || '批量删除失败');
    }
  };

  return (
    <div>
      <h2 style={{ fontSize: '1.875rem', marginBottom: '32px' }}>DC 账号管理</h2>

      {(error || message) && (
        <div className={`alert ${error ? 'alert-error' : 'alert-success'}`}>
          {error || message}
        </div>
      )}

      <div className="card">
        <h3 className="card-title">添加新账号 Token</h3>
        <form onSubmit={addToken} className="stack-form">
          <div style={{ position: 'relative' }}>
            <Key size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              style={{ paddingLeft: '40px' }}
              value={newToken}
              onChange={(e) => { setNewToken(e.target.value); setError(''); setMessage(''); }}
              placeholder="粘贴 Discord 用户 Token"
            />
          </div>
          <div style={{ position: 'relative' }}>
            <Tag size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              style={{ paddingLeft: '40px' }}
              value={newNote}
              maxLength={100}
              onChange={(e) => { setNewNote(e.target.value); setError(''); setMessage(''); }}
              placeholder="备注，例如：美区小号 1 / 备用号 / 群 A 专用"
            />
          </div>
          <button type="submit" className="btn-primary" style={{ width: 'auto', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Plus size={18} /> 添加账号
          </button>
        </form>
      </div>

      <div className="card">
        <div className="card-toolbar">
          <h3 className="card-title" style={{ marginBottom: 0 }}>账号列表</h3>
          <button
            className="btn-danger"
            onClick={bulkDeleteTokens}
            disabled={selectedIds.length === 0}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
          >
            <Trash2 size={16} /> 删除所选 {selectedIds.length > 0 ? `(${selectedIds.length})` : ''}
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th style={{ width: '44px' }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  aria-label="选择全部账号"
                />
              </th>
              <th>ID</th>
              <th>备注</th>
              <th>Token</th>
              <th>状态</th>
              <th>失败次数</th>
              <th>最近检测</th>
              <th>下次检测</th>
              <th>最后使用</th>
              <th>下次重试</th>
              <th style={{ textAlign: 'right' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {tokens.map(t => (
              <tr key={t.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(t.id)}
                    onChange={() => toggleSelected(t.id)}
                    disabled={t.status === 'online'}
                    aria-label={`选择账号 ${t.id}`}
                  />
                </td>
                <td>{t.id}</td>
                <td style={{ minWidth: '180px' }}>
                  {editingId === t.id ? (
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                      <input
                        value={editingNote}
                        maxLength={100}
                        onChange={(e) => setEditingNote(e.target.value)}
                        placeholder="账号备注"
                        style={{ minWidth: '140px' }}
                      />
                      <button onClick={() => saveNote(t.id)} className="btn-secondary" style={{ padding: '6px' }} title="保存备注">
                        <Check size={16} />
                      </button>
                      <button onClick={() => setEditingId(null)} className="btn-secondary" style={{ padding: '6px' }} title="取消编辑">
                        <X size={16} />
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <span className={t.note ? '' : 'muted'}>{t.note || '未备注'}</span>
                      <button onClick={() => startEditNote(t)} className="btn-secondary" style={{ padding: '6px' }} title="编辑备注">
                        <Pencil size={14} />
                      </button>
                    </div>
                  )}
                </td>
                <td style={{ fontFamily: 'monospace', maxWidth: '220px', wordBreak: 'break-all' }}>{t.token.substring(0, 10)}****************</td>
                <td>
                  <span className={`badge badge-${t.status}`}>
                    {statusLabel[t.status] || t.status}
                  </span>
                </td>
                <td>{t.failure_count}</td>
                <td>{formatTime(t.last_checked_at)}</td>
                <td>{formatTime(t.next_check_at)}</td>
                <td>{formatTime(t.last_used)}</td>
                <td>
                  <div>{formatTime(t.next_retry_at)}</div>
                  {t.error_message && (
                    <div className="text-warning" style={{ marginTop: '6px', maxWidth: '260px', whiteSpace: 'normal' }}>
                      {t.error_message}
                    </div>
                  )}
                </td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                  <button
                    onClick={() => checkToken(t.id)}
                    className="btn-secondary"
                    style={{ padding: '6px', marginRight: '8px' }}
                    title="检测 Token"
                    disabled={checkingId === t.id || t.status === 'online' || t.status === 'disabled'}
                  >
                    <SearchCheck size={16} />
                  </button>
                  <button
                    onClick={() => checkTokenServers(t.id)}
                    className="btn-secondary"
                    style={{ padding: '6px', marginRight: '8px' }}
                    title="检查是否加入监控服务器"
                    disabled={checkingId === t.id || t.status === 'disabled'}
                  >
                    <Server size={16} />
                  </button>
                  {t.status === 'disabled' ? (
                    <button onClick={() => updateStatus(t.id, 'standby')} className="btn-secondary" style={{ padding: '6px', marginRight: '8px' }} title="恢复待命">
                      <RotateCcw size={16} />
                    </button>
                  ) : (
                    <button onClick={() => updateStatus(t.id, 'disabled')} className="btn-secondary" style={{ padding: '6px', marginRight: '8px' }} title="禁用账号">
                      <Ban size={16} />
                    </button>
                  )}
                  <button onClick={() => deleteToken(t.id)} className="btn-danger" style={{ padding: '6px' }} title="删除账号">
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
            {tokens.length === 0 && (
              <tr>
                <td colSpan={11} className="empty">暂未添加任何账号</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default Tokens;
