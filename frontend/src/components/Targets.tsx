import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Download, FileDown, Flame, Hash, Pencil, Plus, Search, Server, Trash2, Upload, User, X } from 'lucide-react';
import { api } from '../api';

type TargetServer = {
  id: number;
  guild_id: string;
  name?: string;
};

type TargetUser = {
  id: number;
  username?: string;
  user_id?: string;
  note?: string;
  highlight_enabled?: boolean;
};

type TargetChannel = {
  id: number;
  channel_id: string;
  note?: string;
};

type TargetExport = {
  version: 2;
  exported_at: string;
  servers: Array<{ guild_id: string; name?: string }>;
  users: Array<{ username: string; user_id?: string; note?: string; highlight_enabled?: boolean }>;
  channels: Array<{ channel_id: string; note?: string }>;
};

type SectionKey = 'servers' | 'users' | 'channels';

const isSnowflakeLike = (value: string) => /^\d{10,30}$/.test(value.trim());
const isUsernameLike = (value: string) => {
  const normalized = value.trim();
  return normalized.length >= 2 && normalized.length <= 100 && !/\s/.test(normalized);
};

const cleanDocField = (value?: string) => (value || '').replace(/[\r\n\t]/g, ' ').trim();
const normalizeSearch = (value?: string) => (value || '').trim().toLowerCase();
const matchesQuery = (values: Array<string | undefined>, query: string) => {
  const normalized = normalizeSearch(query);
  if (!normalized) return true;
  return values.some((value) => normalizeSearch(value).includes(normalized));
};

const splitDocLine = (line: string) => {
  if (line.includes('\t')) {
    return line.split('\t').map((part) => part.trim());
  }
  if (line.includes(',')) {
    return line.split(',').map((part) => part.trim());
  }
  return line.split(/\s{2,}/).map((part) => part.trim());
};

const formatTargetsDocument = (payload: TargetExport) => {
  const lines = [
    '# DC-TG Monitor 目标导入文档',
    '# 每行一条；字段可以用 Tab、英文逗号，或两个以上空格分隔；备注可留空。',
    '',
    '[服务器]',
    '服务器ID\t备注',
    ...payload.servers.map((item) => `${cleanDocField(item.guild_id)}\t${cleanDocField(item.name)}`),
    '',
    '[用户]',
    '用户名\t备注\t锁定用户ID(可选)\t高亮(可选)',
    ...payload.users.map((item) => `${cleanDocField(item.username)}\t${cleanDocField(item.note)}\t${cleanDocField(item.user_id)}\t${item.highlight_enabled ? '高亮' : ''}`),
    '',
    '[频道]',
    '频道ID\t备注',
    ...payload.channels.map((item) => `${cleanDocField(item.channel_id)}\t${cleanDocField(item.note)}`),
    '',
  ];
  return lines.join('\n');
};

const parseTargetsDocument = (content: string): TargetExport => {
  const parsed: TargetExport = {
    version: 2,
    exported_at: new Date().toISOString(),
    servers: [],
    users: [],
    channels: [],
  };
  let section: SectionKey | null = null;

  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || line.startsWith('//')) continue;

    const header = line.replace(/^\[|\]$/g, '').trim().toLowerCase();
    if (['服务器', 'servers', 'server'].includes(header)) {
      section = 'servers';
      continue;
    }
    if (['用户', 'users', 'user'].includes(header)) {
      section = 'users';
      continue;
    }
    if (['频道', 'channels', 'channel'].includes(header)) {
      section = 'channels';
      continue;
    }

    const columns = splitDocLine(line);
    const first = columns[0] || '';
    if (!first || /^(服务器id|guild_id|用户名|username|频道id|channel_id)$/i.test(first)) continue;

    if (section === 'servers') {
      parsed.servers.push({ guild_id: first, name: columns[1] || undefined });
    } else if (section === 'users') {
      parsed.users.push({
        username: first,
        note: columns[1] || undefined,
        user_id: columns[2] || undefined,
        highlight_enabled: ['1', 'true', 'yes', 'y', '高亮', '火焰'].includes((columns[3] || '').trim().toLowerCase()),
      });
    } else if (section === 'channels') {
      parsed.channels.push({ channel_id: first, note: columns[1] || undefined });
    }
  }

  return parsed;
};

const Targets = () => {
  const [servers, setServers] = useState<TargetServer[]>([]);
  const [users, setUsers] = useState<TargetUser[]>([]);
  const [channels, setChannels] = useState<TargetChannel[]>([]);
  const [activeSection, setActiveSection] = useState<SectionKey>('users');

  const [newServerId, setNewServerId] = useState('');
  const [newServerName, setNewServerName] = useState('');
  const [newUsername, setNewUsername] = useState('');
  const [newUserNote, setNewUserNote] = useState('');
  const [newUserHighlight, setNewUserHighlight] = useState(false);
  const [newChannelId, setNewChannelId] = useState('');
  const [newChannelNote, setNewChannelNote] = useState('');

  const [serverQuery, setServerQuery] = useState('');
  const [userQuery, setUserQuery] = useState('');
  const [channelQuery, setChannelQuery] = useState('');
  const [selectedServerIds, setSelectedServerIds] = useState<number[]>([]);
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [selectedChannelIds, setSelectedChannelIds] = useState<number[]>([]);

  const [editingServerId, setEditingServerId] = useState<number | null>(null);
  const [editingServerName, setEditingServerName] = useState('');
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [editingUserNote, setEditingUserNote] = useState('');
  const [editingUserHighlight, setEditingUserHighlight] = useState(false);
  const [editingChannelId, setEditingChannelId] = useState<number | null>(null);
  const [editingChannelNote, setEditingChannelNote] = useState('');

  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const importInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const filteredServers = useMemo(
    () => servers.filter((server) => matchesQuery([server.guild_id, server.name], serverQuery)),
    [servers, serverQuery],
  );
  const filteredUsers = useMemo(
    () => users.filter((user) => matchesQuery([user.username, user.note, user.user_id, user.highlight_enabled ? '高亮 火焰' : undefined], userQuery)),
    [users, userQuery],
  );
  const filteredChannels = useMemo(
    () => channels.filter((channel) => matchesQuery([channel.channel_id, channel.note], channelQuery)),
    [channels, channelQuery],
  );

  const fetchData = async () => {
    try {
      const [serverData, userData, channelData] = await Promise.all([
        api.get('/targets/servers'),
        api.get('/targets/users'),
        api.get('/targets/channels'),
      ]);
      setServers(serverData);
      setUsers(userData);
      setChannels(channelData);
      setSelectedServerIds((current) => current.filter((id) => serverData.some((item: TargetServer) => item.id === id)));
      setSelectedUserIds((current) => current.filter((id) => userData.some((item: TargetUser) => item.id === id)));
      setSelectedChannelIds((current) => current.filter((id) => channelData.some((item: TargetChannel) => item.id === id)));
      setError('');
    } catch (err: any) {
      setError(err.message || '读取监控目标失败');
    }
  };

  const resetAlerts = () => {
    setError('');
    setMessage('');
  };

  const toggleSelected = (id: number, selectedIds: number[], setSelectedIds: (value: number[]) => void) => {
    setSelectedIds(selectedIds.includes(id) ? selectedIds.filter((item) => item !== id) : [...selectedIds, id]);
  };

  const toggleSelectAll = (ids: number[], selectedIds: number[], setSelectedIds: (value: number[]) => void) => {
    const allSelected = ids.length > 0 && ids.every((id) => selectedIds.includes(id));
    setSelectedIds(allSelected ? selectedIds.filter((id) => !ids.includes(id)) : Array.from(new Set([...selectedIds, ...ids])));
  };

  const addServer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isSnowflakeLike(newServerId)) {
      setError('服务器 Guild ID 必须是 10-30 位数字');
      return;
    }
    try {
      await api.post('/targets/servers', { guild_id: newServerId.trim(), name: newServerName.trim() || undefined });
      setNewServerId('');
      setNewServerName('');
      setMessage('服务器目标已添加');
      await fetchData();
    } catch (err: any) {
      setError(err.message || '添加服务器目标失败');
    }
  };

  const addUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isUsernameLike(newUsername)) {
      setError('Discord 用户名长度需为 2-100 位，且不能包含空格');
      return;
    }
    try {
      await api.post('/targets/users', {
        username: newUsername.trim(),
        note: newUserNote.trim() || undefined,
        highlight_enabled: newUserHighlight,
      });
      setNewUsername('');
      setNewUserNote('');
      setNewUserHighlight(false);
      setMessage('用户目标已添加，系统将在首次匹配到发言时自动锁定用户 ID');
      await fetchData();
    } catch (err: any) {
      setError(err.message || '添加用户目标失败');
    }
  };

  const addChannel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isSnowflakeLike(newChannelId)) {
      setError('频道 ID 必须是 10-30 位数字');
      return;
    }
    try {
      await api.post('/targets/channels', { channel_id: newChannelId.trim(), note: newChannelNote.trim() || undefined });
      setNewChannelId('');
      setNewChannelNote('');
      setMessage('频道备注已添加');
      await fetchData();
    } catch (err: any) {
      setError(err.message || '添加频道备注失败');
    }
  };

  const startServerEdit = (server: TargetServer) => {
    setEditingServerId(server.id);
    setEditingServerName(server.name || '');
  };

  const saveServerName = async (id: number) => {
    try {
      await api.patch(`/targets/servers/${id}`, { name: editingServerName.trim() || undefined });
      setEditingServerId(null);
      setEditingServerName('');
      setMessage('服务器备注已保存');
      await fetchData();
    } catch (err: any) {
      setError(err.message || '保存服务器备注失败');
    }
  };

  const startUserEdit = (user: TargetUser) => {
    setEditingUserId(user.id);
    setEditingUserNote(user.note || '');
    setEditingUserHighlight(Boolean(user.highlight_enabled));
  };

  const saveUserNote = async (id: number) => {
    try {
      await api.patch(`/targets/users/${id}`, {
        note: editingUserNote.trim() || undefined,
        highlight_enabled: editingUserHighlight,
      });
      setEditingUserId(null);
      setEditingUserNote('');
      setEditingUserHighlight(false);
      setMessage('用户备注已保存');
      await fetchData();
    } catch (err: any) {
      setError(err.message || '保存用户备注失败');
    }
  };

  const startChannelEdit = (channel: TargetChannel) => {
    setEditingChannelId(channel.id);
    setEditingChannelNote(channel.note || '');
  };

  const saveChannelNote = async (id: number) => {
    try {
      await api.patch(`/targets/channels/${id}`, { note: editingChannelNote.trim() || undefined });
      setEditingChannelId(null);
      setEditingChannelNote('');
      setMessage('频道备注已保存');
      await fetchData();
    } catch (err: any) {
      setError(err.message || '保存频道备注失败');
    }
  };

  const removeServer = async (id: number) => {
    if (!confirm('确定要删除这个服务器目标吗？')) return;
    await api.delete(`/targets/servers/${id}`);
    await fetchData();
  };

  const removeUser = async (id: number) => {
    if (!confirm('确定要删除这个用户目标吗？')) return;
    await api.delete(`/targets/users/${id}`);
    await fetchData();
  };

  const removeChannel = async (id: number) => {
    if (!confirm('确定要删除这个频道备注吗？')) return;
    await api.delete(`/targets/channels/${id}`);
    await fetchData();
  };

  const bulkDeleteServers = async () => {
    if (selectedServerIds.length === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedServerIds.length} 个服务器目标吗？`)) return;
    const res = await api.post('/targets/servers/bulk-delete', { ids: selectedServerIds });
    setSelectedServerIds([]);
    setMessage(`已删除 ${res.deleted_ids.length} 个服务器目标`);
    await fetchData();
  };

  const bulkDeleteUsers = async () => {
    if (selectedUserIds.length === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedUserIds.length} 个用户目标吗？`)) return;
    const res = await api.post('/targets/users/bulk-delete', { ids: selectedUserIds });
    setSelectedUserIds([]);
    setMessage(`已删除 ${res.deleted_ids.length} 个用户目标`);
    await fetchData();
  };

  const bulkDeleteChannels = async () => {
    if (selectedChannelIds.length === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedChannelIds.length} 个频道备注吗？`)) return;
    const res = await api.post('/targets/channels/bulk-delete', { ids: selectedChannelIds });
    setSelectedChannelIds([]);
    setMessage(`已删除 ${res.deleted_ids.length} 个频道备注`);
    await fetchData();
  };

  const exportTargets = () => {
    const payload: TargetExport = {
      version: 2,
      exported_at: new Date().toISOString(),
      servers: servers.map((item) => ({
        guild_id: item.guild_id,
        name: item.name || undefined,
      })),
      users: users.map((item) => ({
        username: item.username || '',
        user_id: item.user_id || undefined,
        note: item.note || undefined,
        highlight_enabled: Boolean(item.highlight_enabled),
      })),
      channels: channels.map((item) => ({
        channel_id: item.channel_id,
        note: item.note || undefined,
      })),
    };

    const blob = new Blob([formatTargetsDocument(payload)], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `targets-${new Date().toISOString().slice(0, 10)}.txt`;
    link.click();
    URL.revokeObjectURL(url);
    setMessage('目标配置已导出');
  };

  const downloadTemplate = () => {
    const payload: TargetExport = {
      version: 2,
      exported_at: new Date().toISOString(),
      servers: [
        { guild_id: '123456789012345678', name: '服务器备注示例' },
      ],
      users: [
        { username: 'abc123', note: '用户备注示例', highlight_enabled: true },
      ],
      channels: [
        { channel_id: '123456789012345678', note: '频道备注示例' },
      ],
    };

    const blob = new Blob([formatTargetsDocument(payload)], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'targets-template.txt';
    link.click();
    URL.revokeObjectURL(url);
    setMessage('模板已下载');
  };

  const importTargets = () => {
    importInputRef.current?.click();
  };

  const handleImportFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    try {
      const content = await file.text();
      const parsed = content.trim().startsWith('{')
        ? (JSON.parse(content) as Partial<TargetExport>)
        : parseTargetsDocument(content);
      const serverItems = Array.isArray(parsed?.servers) ? parsed!.servers : [];
      const userItems = Array.isArray(parsed?.users) ? parsed!.users : [];
      const channelItems = Array.isArray(parsed?.channels) ? parsed!.channels : [];

      let imported = 0;
      let skipped = 0;

      const existingServerIds = new Set(servers.map((item) => item.guild_id));
      const existingUsernames = new Set(users.map((item) => (item.username || '').toLowerCase()));
      const existingChannelIds = new Set(channels.map((item) => item.channel_id));

      for (const item of serverItems) {
        const guildId = String(item.guild_id || '').trim();
        if (!isSnowflakeLike(guildId) || existingServerIds.has(guildId)) {
          skipped += 1;
          continue;
        }
        try {
          await api.post('/targets/servers', { guild_id: guildId, name: item.name?.trim() || undefined });
          existingServerIds.add(guildId);
          imported += 1;
        } catch {
          skipped += 1;
        }
      }

      for (const item of userItems) {
        const username = String(item.username || '').trim();
        const normalizedUsername = username.toLowerCase();
        if (!isUsernameLike(username) || existingUsernames.has(normalizedUsername)) {
          skipped += 1;
          continue;
        }
        try {
          await api.post('/targets/users', {
            username,
            user_id: item.user_id?.trim() || undefined,
            note: item.note?.trim() || undefined,
            highlight_enabled: Boolean(item.highlight_enabled),
          });
          existingUsernames.add(normalizedUsername);
          imported += 1;
        } catch {
          skipped += 1;
        }
      }

      for (const item of channelItems) {
        const channelId = String(item.channel_id || '').trim();
        if (!isSnowflakeLike(channelId) || existingChannelIds.has(channelId)) {
          skipped += 1;
          continue;
        }
        try {
          await api.post('/targets/channels', {
            channel_id: channelId,
            note: item.note?.trim() || undefined,
          });
          existingChannelIds.add(channelId);
          imported += 1;
        } catch {
          skipped += 1;
        }
      }

      await fetchData();
      setMessage(`导入完成：新增 ${imported} 项，跳过 ${skipped} 项`);
    } catch (err: any) {
      setError(err.message || '导入失败，请确认文档格式正确');
    }
  };

  const sectionTabs = [
    { key: 'servers' as SectionKey, label: '服务器', count: servers.length, icon: <Server size={16} /> },
    { key: 'users' as SectionKey, label: '用户', count: users.length, icon: <User size={16} /> },
    { key: 'channels' as SectionKey, label: '频道备注', count: channels.length, icon: <Hash size={16} /> },
  ];

  const renderToolbar = (
    query: string,
    setQuery: (value: string) => void,
    total: number,
    filtered: number,
    placeholder: string,
  ) => (
    <div className="target-toolbar">
      <label className="target-search">
        <Search size={16} />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={placeholder} />
      </label>
      <span className="target-count">显示 {filtered} / {total}</span>
    </div>
  );

  const renderEditActions = (onSave: () => void, onCancel: () => void) => (
    <div className="row-actions">
      <button type="button" className="btn-secondary icon-button" onClick={onSave} title="保存">
        <Check size={16} />
      </button>
      <button type="button" className="btn-secondary icon-button" onClick={onCancel} title="取消">
        <X size={16} />
      </button>
    </div>
  );

  const renderRowActions = (onEdit: () => void, onDelete: () => void, deleteTitle: string) => (
    <div className="row-actions">
      <button type="button" className="btn-secondary icon-button" onClick={onEdit} title="编辑备注">
        <Pencil size={16} />
      </button>
      <button type="button" className="btn-danger icon-button" onClick={onDelete} title={deleteTitle}>
        <Trash2 size={16} />
      </button>
    </div>
  );

  const renderServers = () => (
    <section className="target-section">
      {(() => {
        const visibleIds = filteredServers.map((server) => server.id);
        const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedServerIds.includes(id));
        return (
          <>
      <div className="target-section-header">
        <div>
          <h3 className="card-title"><Server size={20} /> 目标服务器</h3>
          <p className="muted">服务器 ID 用来限定监控范围，备注只用于你自己识别。</p>
        </div>
      </div>

      <form onSubmit={addServer} className="target-add-form">
        <input value={newServerId} onChange={(e) => { setNewServerId(e.target.value); resetAlerts(); }} placeholder="Discord 服务器 Guild ID" />
        <input value={newServerName} onChange={(e) => { setNewServerName(e.target.value); resetAlerts(); }} placeholder="服务器备注（可选）" />
        <button type="submit" className="btn-primary"><Plus size={18} /> 添加服务器</button>
      </form>

      {renderToolbar(serverQuery, setServerQuery, servers.length, filteredServers.length, '搜索服务器 ID / 备注')}

      <div className="target-bulk-bar">
        <button type="button" className="btn-danger" onClick={bulkDeleteServers} disabled={selectedServerIds.length === 0}>
          <Trash2 size={16} /> 删除所选{selectedServerIds.length > 0 ? ` (${selectedServerIds.length})` : ''}
        </button>
      </div>

      <table className="compact-table">
        <thead>
          <tr>
            <th style={{ width: '44px' }}>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => toggleSelectAll(visibleIds, selectedServerIds, setSelectedServerIds)}
                aria-label="选择全部服务器目标"
              />
            </th>
            <th>服务器 ID</th>
            <th>备注</th>
            <th style={{ textAlign: 'right' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {filteredServers.map((server) => (
            <tr key={server.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedServerIds.includes(server.id)}
                  onChange={() => toggleSelected(server.id, selectedServerIds, setSelectedServerIds)}
                  aria-label={`选择服务器 ${server.guild_id}`}
                />
              </td>
              <td className="id-cell">{server.guild_id}</td>
              <td>
                {editingServerId === server.id ? (
                  <input value={editingServerName} onChange={(e) => setEditingServerName(e.target.value)} placeholder="服务器备注" />
                ) : (
                  <span className="cell-text">{server.name || '-'}</span>
                )}
              </td>
              <td style={{ textAlign: 'right' }}>
                {editingServerId === server.id
                  ? renderEditActions(() => saveServerName(server.id), () => setEditingServerId(null))
                  : renderRowActions(() => startServerEdit(server), () => removeServer(server.id), '删除服务器')}
              </td>
            </tr>
          ))}
          {filteredServers.length === 0 && (
            <tr><td colSpan={4} className="empty">暂无服务器目标</td></tr>
          )}
        </tbody>
      </table>
          </>
        );
      })()}
    </section>
  );

  const renderUsers = () => (
    <section className="target-section">
      {(() => {
        const visibleIds = filteredUsers.map((user) => user.id);
        const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedUserIds.includes(id));
        return (
          <>
      <div className="target-section-header">
        <div>
          <h3 className="card-title"><User size={20} /> 目标用户</h3>
          <p className="muted">按唯一用户名匹配，首次命中后自动锁定用户 ID；备注会用于 Telegram 推送。</p>
        </div>
      </div>

      <form onSubmit={addUser} className="target-add-form target-add-form-user">
        <input value={newUsername} onChange={(e) => { setNewUsername(e.target.value); resetAlerts(); }} placeholder="Discord 用户名，例如 abc123" />
        <input value={newUserNote} onChange={(e) => { setNewUserNote(e.target.value); resetAlerts(); }} placeholder="中文备注，例如 大户 / 项目方 / 重点观察" />
        <label className="inline-checkbox">
          <input
            type="checkbox"
            checked={newUserHighlight}
            onChange={(e) => { setNewUserHighlight(e.target.checked); resetAlerts(); }}
          />
          <Flame size={16} /> 高亮推送
        </label>
        <button type="submit" className="btn-primary"><Plus size={18} /> 添加用户</button>
      </form>

      {renderToolbar(userQuery, setUserQuery, users.length, filteredUsers.length, '搜索用户名 / 备注 / 用户 ID')}

      <div className="target-bulk-bar">
        <button type="button" className="btn-danger" onClick={bulkDeleteUsers} disabled={selectedUserIds.length === 0}>
          <Trash2 size={16} /> 删除所选{selectedUserIds.length > 0 ? ` (${selectedUserIds.length})` : ''}
        </button>
      </div>

      <table className="compact-table">
        <thead>
          <tr>
            <th style={{ width: '44px' }}>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => toggleSelectAll(visibleIds, selectedUserIds, setSelectedUserIds)}
                aria-label="选择全部用户目标"
              />
            </th>
            <th>用户名</th>
            <th>备注</th>
            <th>高亮</th>
            <th>锁定用户 ID</th>
            <th>状态</th>
            <th style={{ textAlign: 'right' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {filteredUsers.map((user) => (
            <tr key={user.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedUserIds.includes(user.id)}
                  onChange={() => toggleSelected(user.id, selectedUserIds, setSelectedUserIds)}
                  aria-label={`选择用户 ${user.username || user.id}`}
                />
              </td>
              <td>{user.username || '-'}</td>
              <td>
                {editingUserId === user.id ? (
                  <input value={editingUserNote} onChange={(e) => setEditingUserNote(e.target.value)} placeholder="中文备注" />
                ) : (
                  <span className="cell-text">{user.note || '-'}</span>
                )}
              </td>
              <td>
                {editingUserId === user.id ? (
                  <label className="table-checkbox">
                    <input
                      type="checkbox"
                      checked={editingUserHighlight}
                      onChange={(e) => setEditingUserHighlight(e.target.checked)}
                    />
                    <Flame size={15} /> 高亮
                  </label>
                ) : (
                  <span className={`badge ${user.highlight_enabled ? 'badge-warning' : 'badge-standby'}`}>
                    {user.highlight_enabled ? '🔥 高亮' : '普通'}
                  </span>
                )}
              </td>
              <td className="id-cell">{user.user_id || '-'}</td>
              <td>
                <span className={`badge ${user.user_id ? 'badge-online' : 'badge-standby'}`}>
                  {user.user_id ? '已锁定' : '待匹配'}
                </span>
              </td>
              <td style={{ textAlign: 'right' }}>
                {editingUserId === user.id
                  ? renderEditActions(() => saveUserNote(user.id), () => setEditingUserId(null))
                  : renderRowActions(() => startUserEdit(user), () => removeUser(user.id), '删除用户')}
              </td>
            </tr>
          ))}
          {filteredUsers.length === 0 && (
            <tr><td colSpan={7} className="empty">暂无用户目标</td></tr>
          )}
        </tbody>
      </table>
          </>
        );
      })()}
    </section>
  );

  const renderChannels = () => (
    <section className="target-section">
      {(() => {
        const visibleIds = filteredChannels.map((channel) => channel.id);
        const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedChannelIds.includes(id));
        return (
          <>
      <div className="target-section-header">
        <div>
          <h3 className="card-title"><Hash size={20} /> 频道备注</h3>
          <p className="muted">频道备注按频道 ID 绑定，Discord 频道改名后仍然显示你的备注。</p>
        </div>
      </div>

      <form onSubmit={addChannel} className="target-add-form">
        <input value={newChannelId} onChange={(e) => { setNewChannelId(e.target.value); resetAlerts(); }} placeholder="Discord 频道 ID" />
        <input value={newChannelNote} onChange={(e) => { setNewChannelNote(e.target.value); resetAlerts(); }} placeholder="频道备注，例如 子网0" />
        <button type="submit" className="btn-primary"><Plus size={18} /> 添加频道备注</button>
      </form>

      {renderToolbar(channelQuery, setChannelQuery, channels.length, filteredChannels.length, '搜索频道 ID / 备注')}

      <div className="target-bulk-bar">
        <button type="button" className="btn-danger" onClick={bulkDeleteChannels} disabled={selectedChannelIds.length === 0}>
          <Trash2 size={16} /> 删除所选{selectedChannelIds.length > 0 ? ` (${selectedChannelIds.length})` : ''}
        </button>
      </div>

      <table className="compact-table">
        <thead>
          <tr>
            <th style={{ width: '44px' }}>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => toggleSelectAll(visibleIds, selectedChannelIds, setSelectedChannelIds)}
                aria-label="选择全部频道备注"
              />
            </th>
            <th>频道 ID</th>
            <th>备注</th>
            <th style={{ textAlign: 'right' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {filteredChannels.map((channel) => (
            <tr key={channel.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedChannelIds.includes(channel.id)}
                  onChange={() => toggleSelected(channel.id, selectedChannelIds, setSelectedChannelIds)}
                  aria-label={`选择频道 ${channel.channel_id}`}
                />
              </td>
              <td className="id-cell">{channel.channel_id}</td>
              <td>
                {editingChannelId === channel.id ? (
                  <input value={editingChannelNote} onChange={(e) => setEditingChannelNote(e.target.value)} placeholder="频道备注" />
                ) : (
                  <span className="cell-text">{channel.note || '-'}</span>
                )}
              </td>
              <td style={{ textAlign: 'right' }}>
                {editingChannelId === channel.id
                  ? renderEditActions(() => saveChannelNote(channel.id), () => setEditingChannelId(null))
                  : renderRowActions(() => startChannelEdit(channel), () => removeChannel(channel.id), '删除频道备注')}
              </td>
            </tr>
          ))}
          {filteredChannels.length === 0 && (
            <tr><td colSpan={4} className="empty">暂无频道备注</td></tr>
          )}
        </tbody>
      </table>
          </>
        );
      })()}
    </section>
  );

  return (
    <div>
      <div className="page-header">
        <h2>监控目标设置</h2>
        <div className="button-row">
          <button type="button" className="btn-secondary" onClick={exportTargets}>
            <Download size={18} /> 导出目标
          </button>
          <button type="button" className="btn-secondary" onClick={downloadTemplate}>
            <FileDown size={18} /> 下载模板
          </button>
          <button type="button" className="btn-secondary" onClick={importTargets}>
            <Upload size={18} /> 导入目标
          </button>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json,text/plain,.txt"
            style={{ display: 'none' }}
            onChange={handleImportFile}
          />
        </div>
      </div>

      {(error || message) && (
        <div className={`alert ${error ? 'alert-error' : 'alert-success'}`}>
          {error || message}
        </div>
      )}

      <div className="target-tabs">
        {sectionTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`target-tab ${activeSection === tab.key ? 'active' : ''}`}
            onClick={() => setActiveSection(tab.key)}
          >
            {tab.icon}
            <span>{tab.label}</span>
            <strong>{tab.count}</strong>
          </button>
        ))}
      </div>

      <div className="card target-panel">
        {activeSection === 'servers' && renderServers()}
        {activeSection === 'users' && renderUsers()}
        {activeSection === 'channels' && renderChannels()}
      </div>
    </div>
  );
};

export default Targets;
