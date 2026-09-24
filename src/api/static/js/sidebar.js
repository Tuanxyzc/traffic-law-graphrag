/**
 * Sidebar Navigation & History Management
 */

const STORAGE_KEY_HISTORY = 'traffic_law_query_history';

// Dữ liệu mẫu ban đầu nếu localStorage chưa có
const DEFAULT_HISTORY = [
  { id: '1', query: 'Nồng độ cồn xe máy phạt bao nhiêu?', timestamp: Date.now() - 3600000 },
  { id: '2', query: 'Vượt đèn đỏ ô tô Nghị định 168/2024', timestamp: Date.now() - 7200000 },
  { id: '3', query: 'Trừ điểm bằng lái xe khi nào áp dụng?', timestamp: Date.now() - 86400000 }
];

export class SidebarManager {
  constructor({ onSelectHistory, onNewChat, onSwitchView }) {
    this.onSelectHistory = onSelectHistory;
    this.onNewChat = onNewChat;
    this.onSwitchView = onSwitchView;

    this.navChat = document.getElementById('nav-chat');
    this.navDocs = document.getElementById('nav-docs');
    this.btnNewChat = document.getElementById('btn-new-chat');
    this.historyList = document.getElementById('history-list');
    this.currentViewTitle = document.getElementById('current-view-title');
    this.systemStatusText = document.getElementById('system-status-text');

    this.initEvents();
    this.renderHistory();
    this.checkHealth();
  }

  initEvents() {
    this.navChat.addEventListener('click', () => {
      this.setActiveNav('chat');
      this.currentViewTitle.textContent = 'Tra cứu & Tư vấn pháp lý';
      if (this.onSwitchView) this.onSwitchView('chat');
    });

    this.navDocs.addEventListener('click', () => {
      this.setActiveNav('docs');
      this.currentViewTitle.textContent = 'Danh mục Văn bản Quy phạm Pháp luật';
      if (this.onSwitchView) this.onSwitchView('docs');
    });

    this.btnNewChat.addEventListener('click', () => {
      this.setActiveNav('chat');
      this.currentViewTitle.textContent = 'Tra cứu & Tư vấn pháp lý';
      if (this.onNewChat) this.onNewChat();
    });
  }

  setActiveNav(viewName) {
    if (viewName === 'chat') {
      this.navChat.classList.add('active');
      this.navDocs.classList.remove('active');
    } else {
      this.navDocs.classList.add('active');
      this.navChat.classList.remove('active');
    }
  }

  getHistory() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_HISTORY);
      if (stored) return JSON.parse(stored);
    } catch {
      // fallback
    }
    return DEFAULT_HISTORY;
  }

  saveQuery(query) {
    const list = this.getHistory();
    // Đưa câu hỏi mới lên đầu, lọc trùng
    const updated = [
      { id: Date.now().toString(), query, timestamp: Date.now() },
      ...list.filter(item => item.query.toLowerCase() !== query.toLowerCase())
    ].slice(0, 15);

    try {
      localStorage.setItem(STORAGE_KEY_HISTORY, JSON.stringify(updated));
    } catch {
      // ignore
    }
    this.renderHistory();
  }

  renderHistory() {
    const items = this.getHistory();
    this.historyList.innerHTML = '';

    if (items.length === 0) {
      this.historyList.innerHTML = '<li style="font-size: 11px; color: var(--color-stone); padding: 6px 8px;">Chưa có lịch sử tra cứu</li>';
      return;
    }

    items.forEach(item => {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.className = 'history-item-btn';
      btn.textContent = item.query;
      btn.title = item.query;
      btn.addEventListener('click', () => {
        if (this.onSelectHistory) this.onSelectHistory(item.query);
      });
      li.appendChild(btn);
      this.historyList.appendChild(li);
    });
  }

  async checkHealth() {
    try {
      const res = await fetch('/health');
      if (res.ok) {
        const data = await res.json();
        const neo4jStatus = data.components?.neo4j || 'ok';
        this.systemStatusText.textContent = `GraphRAG Neo4j (${neo4jStatus})`;
      }
    } catch {
      this.systemStatusText.textContent = 'GraphRAG (Chế độ mô phỏng)';
    }
  }
}
