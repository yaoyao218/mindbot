import Dexie from 'https://unpkg.com/dexie@3.2.4/dist/dexie.mjs';

export const db = new Dexie('MindBotLocalDB');

// v1：初始 Schema
db.version(1).stores({
  archives:      '++id, date, start_date, end_date',
  conversations: '++id, timestamp, role, content',
  user_settings: 'key',
});

// v2：conversations 加入 &msg_key 唯一索引（& = unique），Dexie 自動遷移
db.version(2).stores({
  archives:      '++id, date, start_date, end_date',
  conversations: '++id, &msg_key, timestamp, role, content',
  user_settings: 'key',
});

/** @returns {Promise<any>} */
export async function getSetting(key, defaultValue) {
  const item = await db.user_settings.get(key);
  return item ? item.value : defaultValue;
}

/** @returns {Promise<void>} */
export async function setSetting(key, value) {
  return db.user_settings.put({ key, value });
}

// msg_key 組合公式（時間戳記 + 角色，確保唯一性）
export function msgKey(m) {
  return `${m.created_at || m.timestamp || Date.now()}_${m.role || 'user'}`;
}
