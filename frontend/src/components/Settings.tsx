import { useEffect, useState } from 'react';
import { Languages, RefreshCw, Save, Send } from 'lucide-react';
import { api } from '../api';

type ForwardFormat = 'original' | 'summary_original' | 'summary_only';

type BalanceInfo = {
  currency?: string;
  total_balance?: string;
  granted_balance?: string;
  topped_up_balance?: string;
};

type AiProvider = 'primary' | 'backup';

const Settings = () => {
  const [tgToken, setTgToken] = useState('');
  const [tgChatId, setTgChatId] = useState('');
  const [aiEnabled, setAiEnabled] = useState(false);
  const [aiApiKey, setAiApiKey] = useState('');
  const [aiBaseUrl, setAiBaseUrl] = useState('https://api.deepseek.com');
  const [aiModel, setAiModel] = useState('deepseek-chat');
  const [aiBackupApiKey, setAiBackupApiKey] = useState('');
  const [aiBackupBaseUrl, setAiBackupBaseUrl] = useState('');
  const [aiBackupModel, setAiBackupModel] = useState('');
  const [aiActiveProvider, setAiActiveProvider] = useState('primary');
  const [aiForwardFormat, setAiForwardFormat] = useState<ForwardFormat>('summary_original');
  const [aiBalanceAvailable, setAiBalanceAvailable] = useState<boolean | null>(null);
  const [aiBalanceInfos, setAiBalanceInfos] = useState<BalanceInfo[]>([]);
  const [aiBalanceProvider, setAiBalanceProvider] = useState<AiProvider>('primary');
  const [balanceLoading, setBalanceLoading] = useState(false);
  const [backupBalanceLoading, setBackupBalanceLoading] = useState(false);
  const [balanceError, setBalanceError] = useState('');
  const [aiTesting, setAiTesting] = useState(false);
  const [primaryAiTesting, setPrimaryAiTesting] = useState(false);
  const [backupAiTesting, setBackupAiTesting] = useState(false);
  const [aiTestResult, setAiTestResult] = useState('');
  const [aiTestProvider, setAiTestProvider] = useState('');
  const [aiTestError, setAiTestError] = useState('');
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    try {
      const data = await api.get('/config');
      setTgToken(data.tg_bot_token || '');
      setTgChatId(data.tg_chat_id || '');
      setAiEnabled(Boolean(data.ai_enabled));
      setAiApiKey(data.ai_api_key || '');
      const isGoogleModel = data.ai_model === 'google' || data.ai_model === 'google-translate';
      setAiBaseUrl(data.ai_base_url === 'https://api.deepseek.com' && isGoogleModel ? '' : (data.ai_base_url || ''));
      setAiModel(data.ai_model || 'deepseek-chat');
      setAiBackupApiKey(data.ai_backup_api_key || '');
      setAiBackupBaseUrl(data.ai_backup_base_url || '');
      setAiBackupModel(data.ai_backup_model || '');
      setAiActiveProvider(data.ai_active_provider || 'primary');
      setAiForwardFormat(data.ai_forward_format || 'summary_original');
      setBalanceError('');
      setAiTestError('');
    } catch (err: any) {
      setError(err.message || '读取设置失败');
    }
  };

  const validate = () => {
    if (!tgToken.trim()) return '请输入 Telegram Bot Token';
    if (!/^\d+:[A-Za-z0-9_-]+$/.test(tgToken.trim())) return 'Telegram Bot Token 格式不正确';
    if (!tgChatId.trim()) return '请输入 Telegram Chat ID';
    if (!/^-?\d+$/.test(tgChatId.trim())) return 'Telegram Chat ID 必须是数字';
    if (aiEnabled) {
      const isGoogle = aiModel.trim() === 'google' || aiModel.trim() === 'google-translate';
      if (!isGoogle) {
        if (!aiApiKey.trim()) return '启用 AI 翻译后，请输入 OpenAI API Key';
        if (!/^https?:\/\//.test(aiBaseUrl.trim())) return 'AI Base URL 必须以 http:// 或 https:// 开头';
      } else {
        if (aiBaseUrl.trim() && !/^https?:\/\//.test(aiBaseUrl.trim())) {
          return 'AI Base URL 必须以 http:// 或 https:// 开头';
        }
      }
      if (!aiModel.trim()) return '请输入 AI 模型名称';
      if (aiBackupBaseUrl.trim() && !/^https?:\/\//.test(aiBackupBaseUrl.trim())) {
        return '备用 AI Base URL 必须以 http:// 或 https:// 开头';
      }
      if ((aiBackupApiKey.trim() || aiBackupBaseUrl.trim() || aiBackupModel.trim())
        && !(aiBackupApiKey.trim() && aiBackupBaseUrl.trim() && aiBackupModel.trim())) {
        return '备用 AI 配置需要同时填写 Key、Base URL 和模型';
      }
    }
    return '';
  };

  const handleSave = async (e: React.FormEvent | React.MouseEvent) => {
    e.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      setMessage('');
      return;
    }

    setLoading(true);
    setError('');
    setMessage('');
    try {
      const saved = await api.put('/config', {
        tg_bot_token: tgToken.trim(),
        tg_chat_id: tgChatId.trim(),
        ai_enabled: aiEnabled,
        ai_api_key: aiApiKey.trim() || null,
        ai_base_url: aiBaseUrl.trim() || 'https://api.deepseek.com',
        ai_model: aiModel.trim() || 'deepseek-chat',
        ai_backup_api_key: aiBackupApiKey.trim() || null,
        ai_backup_base_url: aiBackupBaseUrl.trim() || null,
        ai_backup_model: aiBackupModel.trim() || null,
        ai_forward_format: aiForwardFormat,
      });
      setAiActiveProvider(saved.ai_active_provider || 'primary');
      setMessage('设置保存成功');
    } catch (err: any) {
      setError(err.message || '保存设置时出错');
    } finally {
      setLoading(false);
    }
  };

  const fetchAiBalance = async (provider: AiProvider) => {
    if (provider === 'backup') {
      setBackupBalanceLoading(true);
    } else {
      setBalanceLoading(true);
    }
    setBalanceError('');
    try {
      const data = await api.get(`/config/ai-balance/${provider}`);
      setAiBalanceAvailable(data.is_available ?? null);
      setAiBalanceInfos(data.balance_infos || []);
      setAiBalanceProvider(provider);
    } catch (err: any) {
      setAiBalanceAvailable(null);
      setAiBalanceInfos([]);
      setBalanceError(err.message || '余额查询失败');
    } finally {
      setBalanceLoading(false);
      setBackupBalanceLoading(false);
    }
  };

  const testAiSummary = async (provider?: AiProvider) => {
    if (provider === 'primary') {
      setPrimaryAiTesting(true);
    } else if (provider === 'backup') {
      setBackupAiTesting(true);
    } else {
      setAiTesting(true);
    }
    setAiTestError('');
    setAiTestResult('');
    setAiTestProvider('');
    try {
      const data = await api.post(provider ? `/config/test-ai/${provider}` : '/config/test-ai');
      setAiTestResult(data.summary || '');
      setAiTestProvider(provider ? (provider === 'backup' ? '备用' : '主用') : '自动');
      await fetchConfig();
    } catch (err: any) {
      setAiTestError(err.message || 'AI 测试失败');
    } finally {
      setAiTesting(false);
      setPrimaryAiTesting(false);
      setBackupAiTesting(false);
    }
  };

  const handleTest = async () => {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      setMessage('');
      return;
    }

    setTesting(true);
    setError('');
    setMessage('');
    try {
      await api.post('/config/test-telegram', { tg_bot_token: tgToken.trim(), tg_chat_id: tgChatId.trim() });
      setMessage('测试消息发送成功');
    } catch (err: any) {
      setError(err.message || '测试消息发送失败');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div>
      <h2 style={{ fontSize: '1.875rem', marginBottom: '32px' }}>系统设置</h2>

      {(error || message) && (
        <div className={`alert ${error ? 'alert-error' : 'alert-success'}`}>
          {error || message}
        </div>
      )}

      <div className="card" style={{ maxWidth: '640px' }}>
        <h3 className="card-title"><Send size={20} /> Telegram 配置</h3>
        <form onSubmit={handleSave}>
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>Telegram Bot Token</label>
            <input
              type="password"
              value={tgToken}
              onChange={(e) => { setTgToken(e.target.value); setError(''); setMessage(''); }}
              placeholder="例如：123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
            />
          </div>
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>目标 Chat ID</label>
            <input
              value={tgChatId}
              onChange={(e) => { setTgChatId(e.target.value); setError(''); setMessage(''); }}
              placeholder="例如：-100123456789 或 123456789"
            />
          </div>
          <div className="button-row">
            <button type="submit" className="btn-primary" disabled={loading}>
              <Save size={18} /> {loading ? '正在保存...' : '保存配置'}
            </button>
            <button type="button" className="btn-secondary" onClick={handleTest} disabled={testing}>
              <Send size={18} /> {testing ? '正在发送...' : '发送测试消息'}
            </button>
          </div>
        </form>
      </div>

      <div className="card" style={{ maxWidth: '640px' }}>
        <h3 className="card-title"><Languages size={20} /> AI 翻译</h3>
        <div className="settings-row" style={{ marginBottom: '20px' }}>
          <div>
            <strong>启用 AI 翻译</strong>
            <p className="muted" style={{ marginTop: '4px' }}>只处理已命中的监控消息，优先自然、完整地翻译为中文，推送时按下面格式输出。</p>
          </div>
          <label className="toggle">
            <input
              type="checkbox"
              checked={aiEnabled}
              onChange={(e) => { setAiEnabled(e.target.checked); setError(''); setMessage(''); }}
            />
            <span>{aiEnabled ? '已启用' : '已关闭'}</span>
          </label>
        </div>

        <div style={{ marginBottom: '20px' }}>
          <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>OpenAI API Key</label>
          <input
            type="password"
            value={aiApiKey}
            onChange={(e) => { setAiApiKey(e.target.value); setError(''); setMessage(''); }}
            placeholder="兼容 OpenAI 接口的 Key，例如 DeepSeek API Key"
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', marginBottom: '20px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>Base URL</label>
            <input
              value={aiBaseUrl}
              onChange={(e) => { setAiBaseUrl(e.target.value); setError(''); setMessage(''); }}
              placeholder="https://api.deepseek.com"
            />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>模型</label>
            <input
              value={aiModel}
              onChange={(e) => {
                const newModel = e.target.value;
                setAiModel(newModel);
                if ((newModel === 'google' || newModel === 'google-translate') && aiBaseUrl === 'https://api.deepseek.com') {
                  setAiBaseUrl('');
                } else if (newModel !== 'google' && newModel !== 'google-translate' && aiBaseUrl === '') {
                  setAiBaseUrl('https://api.deepseek.com');
                }
                setError('');
                setMessage('');
              }}
              placeholder="deepseek-chat"
            />
            <p className="muted" style={{ fontSize: '12px', marginTop: '4px' }}>
              输入 <code>google</code> 可使用免费的谷歌翻译接口（此时无需配置 Key 和 Base URL）
            </p>
          </div>
        </div>

        <div className="balance-panel" style={{ marginBottom: '20px' }}>
          <div className="settings-row" style={{ marginBottom: '16px' }}>
            <div>
              <strong>备用 AI API</strong>
              <p className="muted" style={{ marginTop: '4px' }}>主 API 失败或返回 503 时自动切换；使用备用时每 30 分钟检测主 API，恢复后自动切回。</p>
            </div>
            <span className={aiActiveProvider === 'backup' ? 'text-warning' : 'text-success'}>
              当前：{aiActiveProvider === 'backup' ? '备用' : '主用'}
            </span>
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>备用 OpenAI API Key</label>
            <input
              type="password"
              value={aiBackupApiKey}
              onChange={(e) => { setAiBackupApiKey(e.target.value); setError(''); setMessage(''); }}
              placeholder="备用兼容 OpenAI 接口的 Key"
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>备用 Base URL</label>
              <input
                value={aiBackupBaseUrl}
                onChange={(e) => { setAiBackupBaseUrl(e.target.value); setError(''); setMessage(''); }}
                placeholder="https://api.example.com/v1"
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>备用模型</label>
              <input
                value={aiBackupModel}
                onChange={(e) => { setAiBackupModel(e.target.value); setError(''); setMessage(''); }}
                placeholder="gpt-5.4-mini"
              />
            </div>
          </div>
        </div>

        <div style={{ marginBottom: '24px' }}>
          <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-muted)' }}>转发格式</label>
          <select
            value={aiForwardFormat}
            onChange={(e) => { setAiForwardFormat(e.target.value as ForwardFormat); setError(''); setMessage(''); }}
          >
            <option value="original">原文</option>
            <option value="summary_original">中文翻译 + 原文</option>
            <option value="summary_only">仅中文</option>
          </select>
        </div>

        <div className="balance-panel">
          <div className="settings-row">
            <div>
              <strong>API 余额</strong>
              <p className="muted" style={{ marginTop: '4px' }}>使用已保存的 API Key 查询，主用和备用可分别检查。</p>
            </div>
            <div className="button-row">
              <button type="button" className="btn-secondary" onClick={() => fetchAiBalance('primary')} disabled={balanceLoading || backupBalanceLoading}>
                <RefreshCw size={16} /> {balanceLoading ? '查询中...' : '查主用余额'}
              </button>
              <button type="button" className="btn-secondary" onClick={() => fetchAiBalance('backup')} disabled={balanceLoading || backupBalanceLoading}>
                <RefreshCw size={16} /> {backupBalanceLoading ? '查询中...' : '查备用余额'}
              </button>
            </div>
          </div>
          {balanceError && <p className="text-warning" style={{ marginTop: '12px' }}>{balanceError}</p>}
          {aiBalanceAvailable !== null && (
            <p className={aiBalanceAvailable ? 'text-success' : 'text-warning'} style={{ marginTop: '12px' }}>
              {aiBalanceProvider === 'backup' ? '备用' : '主用'}状态：{aiBalanceAvailable ? '可用' : '不可用'}
            </p>
          )}
          {aiBalanceInfos.length > 0 && (
            <div className="balance-grid">
              {aiBalanceInfos.map((item, index) => (
                <div key={`${item.currency || 'balance'}-${index}`} className="balance-item">
                  <span className="muted">{item.currency || '余额'}</span>
                  <strong>{item.total_balance ?? '-'}</strong>
                  <small>赠送 {item.granted_balance ?? '-'} / 充值 {item.topped_up_balance ?? '-'}</small>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="balance-panel">
          <div className="settings-row">
            <div>
              <strong>AI 连接测试</strong>
              <p className="muted" style={{ marginTop: '4px' }}>可单独测试主用/备用，也可测试自动主备切换。</p>
            </div>
            <div className="button-row">
              <button type="button" className="btn-secondary" onClick={() => testAiSummary('primary')} disabled={aiTesting || primaryAiTesting || backupAiTesting}>
                <Languages size={16} /> {primaryAiTesting ? '测试中...' : '测主用'}
              </button>
              <button type="button" className="btn-secondary" onClick={() => testAiSummary('backup')} disabled={aiTesting || primaryAiTesting || backupAiTesting}>
                <Languages size={16} /> {backupAiTesting ? '测试中...' : '测备用'}
              </button>
              <button type="button" className="btn-secondary" onClick={() => testAiSummary()} disabled={aiTesting || primaryAiTesting || backupAiTesting}>
                <Languages size={16} /> {aiTesting ? '测试中...' : '测自动切换'}
              </button>
            </div>
          </div>
          {aiTestError && <p className="text-warning" style={{ marginTop: '12px' }}>{aiTestError}</p>}
          {aiTestResult && (
            <div className="test-result">
              <span className="muted">{aiTestProvider ? `${aiTestProvider}测试结果` : '测试结果'}</span>
              <p>{aiTestResult}</p>
            </div>
          )}
        </div>

        <button type="button" className="btn-primary" disabled={loading} onClick={handleSave}>
          <Save size={18} /> {loading ? '正在保存...' : '保存 AI 配置'}
        </button>
      </div>

      <div className="card" style={{ maxWidth: '640px' }}>
        <h3 className="card-title">系统说明</h3>
        <p className="muted">
          系统会在可用 DC 账号之间自动切换。Token 登录失败会标记为无效，连接异常会进入退避重试，手动禁用的账号不会参与轮换。运行日志仅保留最近 1 小时。
        </p>
      </div>
    </div>
  );
};

export default Settings;
