import { getD1 } from './index';

export class RateLimitError extends Error {
  constructor() {
    super('操作太頻繁，請稍後再試。');
  }
}

export async function enforceUserRateLimit(userId: string, action: string, limit = 12, windowMinutes = 15) {
  const windowMs = windowMinutes * 60 * 1000;
  const windowStart = Math.floor(Date.now() / windowMs) * windowMs;
  const row = await getD1().prepare(`
    INSERT INTO api_rate_limits (user_id, action, window_started_at, request_count, updated_at)
    VALUES (?, ?, ?, 1, ?)
    ON CONFLICT(user_id, action, window_started_at)
    DO UPDATE SET request_count = request_count + 1, updated_at = excluded.updated_at
    RETURNING request_count
  `).bind(userId, action, windowStart, new Date().toISOString()).first<{ request_count: number }>();

  if (!row || Number(row.request_count) > limit) throw new RateLimitError();
}
