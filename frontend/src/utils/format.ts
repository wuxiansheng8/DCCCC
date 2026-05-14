const SHANGHAI_TIME_ZONE = 'Asia/Shanghai';

const parseBackendDate = (value: string) => {
  const normalized = value.includes('T') ? value : value.replace(' ', 'T');
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(normalized)) {
    return new Date(`${normalized}Z`);
  }
  return new Date(normalized);
};

export const formatShanghaiTime = (value?: string) => {
  if (!value) {
    return '-';
  }

  const date = parseBackendDate(value);
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
};

export const formatDurationSeconds = (totalSeconds?: number) => {
  const seconds = Math.max(0, Math.floor(totalSeconds || 0));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  if (days > 0) {
    return `${days}天 ${hours}小时 ${minutes}分 ${remainingSeconds}秒`;
  }
  if (hours > 0) {
    return `${hours}小时 ${minutes}分 ${remainingSeconds}秒`;
  }
  if (minutes > 0) {
    return `${minutes}分 ${remainingSeconds}秒`;
  }
  return `${remainingSeconds}秒`;
};

export const translateLogLevel = (level: string) => {
  const labels: Record<string, string> = {
    error: '错误',
    success: '成功',
    warning: '警告',
    info: '信息',
  };
  return labels[level] || level;
};

const translateReason = (reason: string) => {
  const normalized = reason.trim();
  const reasons: Record<string, string> = {
    'Discord rejected the token.': 'Discord 拒绝了这个 Token，可能已经失效。',
    'Discord rate limited token validation.': 'Discord 限制了本次 Token 检测。',
    'Discord token validation timed out.': 'Discord Token 检测超时。',
    'Login failed. Token is invalid.': '登录失败，Token 无效。',
    'Discord client disconnected.': 'Discord 连接已断开。',
  };

  if (reasons[normalized]) {
    return reasons[normalized];
  }
  if (normalized.startsWith('Discord token validation returned HTTP ')) {
    return normalized.replace('Discord token validation returned HTTP ', 'Discord Token 检测返回 HTTP ');
  }
  if (normalized.startsWith('Discord token validation request failed: ')) {
    return normalized.replace('Discord token validation request failed: ', 'Discord Token 检测请求失败：');
  }
  if (normalized.startsWith('Discord HTTP error: ')) {
    return normalized.replace('Discord HTTP error: ', 'Discord HTTP 错误：');
  }
  if (normalized.startsWith('Discord client crashed: ')) {
    return normalized.replace('Discord client crashed: ', 'Discord 客户端异常退出：');
  }
  if (normalized.startsWith('Token check failed: ')) {
    return normalized.replace('Token check failed: ', 'Token 检测失败：');
  }

  return normalized;
};

export const translateSystemLog = (message: string) => {
  const rules: Array<[RegExp, string | ((...args: string[]) => string)]> = [
    [/^Manual token check passed with warning:\s*(.+?)\s*-\s*(.+)$/i, (_, token, warning) => `手动检测通过，但有提醒：${token} - ${warning}`],
    [/^Manual token check passed:\s*(.+?)\.$/i, (_, token) => `手动检测通过：${token}`],
    [/^Manual token check failed:\s*(.+?)\s*-\s*(.+)$/i, (_, token, reason) => `手动检测失败：${token} - ${translateReason(reason)}`],
    [/^Token check passed with warning:\s*(.+?)\s*-\s*(.+)$/i, (_, token, warning) => `Token 检测通过，但有提醒：${token} - ${warning}`],
    [/^Token check passed:\s*(.+?)\.$/i, (_, token) => `Token 检测通过：${token}`],
    [/^Token check failed:\s*(.+?)\s*-\s*(.+)$/i, (_, token, reason) => `Token 检测失败：${token} - ${translateReason(reason)}`],
    [/^Token pool is low, but Telegram is not configured\.$/i, '号池不足，但尚未配置 Telegram。'],
    [/^Low token pool alert sent\.\s*Available tokens:\s*(\d+)\.$/i, (_, count) => `已发送号池不足告警，可用账号：${count}`],
    [/^Forwarded (live|backfill) message from (.+?) in (.+?)\.$/i, (_, source, user, server) => `${source === 'live' ? '实时' : '回补'}消息已转发：${user} / ${server}`],
    [/^Failed to forward message from (.+?):\s*(.+)$/i, (_, user, reason) => `消息转发失败：${user}，原因：${translateReason(reason)}`],
    [/^Backfill skipped for (.+?) \/ (.+?): missing permissions\.$/i, (_, server, channel) => `回补已跳过：${server} / ${channel}，权限不足`],
    [/^Backfill failed for (.+?) \/ (.+?):\s*(.+)$/i, (_, server, channel, reason) => `回补失败：${server} / ${channel} - ${translateReason(reason)}`],
    [/^DC Account (.+?) is online and monitoring\.$/i, (_, account) => `DC 账号 ${account} 已上线并开始监控`],
    [/^Locked target username (.+?) to user ID (.+?)\.$/i, (_, username, userId) => `目标用户名已锁定：${username} -> ${userId}`],
    [/^Telegram test message sent successfully\.$/i, 'Telegram 测试消息发送成功。'],
    [/^System monitoring stopped\.$/i, '系统监控已停止。'],
    [/^System monitoring interrupted by backend restart\.$/i, '后端重启，稳定运行时间已归零。'],
    [/^Token switch:\s*(\d+)\s*->\s*(\d+)\.$/i, (_, from, to) => `Token 已无感切换：${from} -> ${to}`],
    [/^Service unavailable:\s*(.+)$/i, (_, reason) => `服务不可用：${translateReason(reason)}`],
  ];

  for (const [pattern, replacement] of rules) {
    if (pattern.test(message)) {
      return message.replace(pattern, replacement as any);
    }
  }

  return message;
};
