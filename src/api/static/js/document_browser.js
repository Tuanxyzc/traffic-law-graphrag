/**
 * Document Browser View
 */

export class DocumentBrowserManager {
  constructor({ onSelectDocument }) {
    this.onSelectDocument = onSelectDocument;
    this.container = document.getElementById('docs-list-container');
    this.docsView = document.getElementById('docs-view');
    this.chatView = document.getElementById('chat-view');

    this.hasLoaded = false;
  }

  show() {
    this.chatView.style.display = 'none';
    this.docsView.style.display = 'flex';

    if (!this.hasLoaded) {
      this.loadDocuments();
    }
  }

  hide() {
    this.docsView.style.display = 'none';
    this.chatView.style.display = 'flex';
  }

  async loadDocuments() {
    this.container.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px; color: var(--color-stone); font-size: 13px; padding: 20px 0;">
        <svg class="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
        <span>Đang tải danh mục văn bản từ Neo4j...</span>
      </div>
    `;

    try {
      const res = await fetch('/api/v1/graph/documents?limit=50');
      if (res.ok) {
        const docs = await res.json();
        this.renderDocuments(docs);
        this.hasLoaded = true;
      } else {
        this.renderFallbackDocs();
      }
    } catch {
      this.renderFallbackDocs();
    }
  }

  renderDocuments(docs) {
    if (!docs || docs.length === 0) {
      this.renderFallbackDocs();
      return;
    }

    this.container.innerHTML = '';
    docs.forEach(doc => {
      const card = document.createElement('div');
      card.className = 'doc-card';
      card.innerHTML = `
        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;">
          <div>
            <h3 class="doc-title">${doc.title || doc.document_id}</h3>
            <div class="doc-meta">
              <span>Mã văn bản: <strong>${doc.document_id}</strong></span>
              <span>Tổng số điều: <strong>${doc.total_articles || 'N/A'}</strong></span>
              ${doc.effective_date ? `<span>Hiệu lực: ${doc.effective_date}</span>` : ''}
            </div>
          </div>
          <button class="suggestion-chip" style="margin: 0;" data-doc="${doc.document_id}">
            <span>Tra cứu</span>
          </button>
        </div>
      `;

      card.querySelector('button').addEventListener('click', () => {
        if (this.onSelectDocument) {
          this.onSelectDocument(doc.document_id);
        }
      });

      this.container.appendChild(card);
    });
  }

  renderFallbackDocs() {
    const fallbackList = [
      {
        document_id: '168_2024_ND-CP',
        title: 'Nghị định 168/2024/NĐ-CP quy định xử phạt vi phạm hành chính về trật tự, an toàn giao thông đường bộ',
        total_articles: 56,
        effective_date: '01/01/2025'
      },
      {
        document_id: 'LUAT_TTATGTDB_2024',
        title: 'Luật Trật tự, an toàn giao thông đường bộ số 36/2024/QH15',
        total_articles: 89,
        effective_date: '01/01/2025'
      },
      {
        document_id: '100_2019_ND-CP',
        title: 'Nghị định 100/2019/NĐ-CP quy định xử phạt vi phạm hành chính lĩnh vực giao thông đường bộ và đường sắt',
        total_articles: 86,
        effective_date: '15/01/2020 (Đã được sửa đổi, bổ sung)'
      },
      {
        document_id: '123_2021_ND-CP',
        title: 'Nghị định 123/2021/NĐ-CP sửa đổi, bổ sung một số điều của các Nghị định xử phạt vi phạm hành chính',
        total_articles: 12,
        effective_date: '01/01/2022'
      }
    ];
    this.renderDocuments(fallbackList);
  }
}
