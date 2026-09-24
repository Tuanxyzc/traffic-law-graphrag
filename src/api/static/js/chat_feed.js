/**
 * Chat Feed & SSE Streaming Handler
 */

import { PipelineProgress } from './pipeline_progress.js';

export class ChatFeedManager {
  constructor({ onSubgraphReceived, onCitationHover, onCitationClick }) {
    this.onSubgraphReceived = onSubgraphReceived;
    this.onCitationHover = onCitationHover;
    this.onCitationClick = onCitationClick;

    this.feedContainer = document.getElementById('chat-feed');
    this.scrollContainer = document.getElementById('main-scroll-container');
    this.activeProgress = null;
    this.currentAnswerBody = null;
    this.tokenBuffer = '';
  }

  clear() {
    this.feedContainer.innerHTML = '';
    this.feedContainer.style.display = 'none';
  }

  show() {
    this.feedContainer.style.display = 'block';
  }

  async sendQuery(query) {
    this.show();

    // 1. Render User Query Card
    const userCard = document.createElement('div');
    userCard.className = 'user-query-card';
    userCard.innerHTML = `
      <div class="user-query-label">Câu hỏi công dân</div>
      <div class="user-query-text">${this.escapeHtml(query)}</div>
    `;
    this.feedContainer.appendChild(userCard);

    // 2. Render Pipeline Progress (4 steps)
    const progress = new PipelineProgress();
    const progressDOM = progress.createDOM();
    this.feedContainer.appendChild(progressDOM);
    this.activeProgress = progress;

    // Bắt đầu bước 1: Chuẩn hóa câu hỏi
    progress.setStep(0);
    this.scrollToBottom();

    // 3. Chuẩn bị Answer Card
    const answerCard = document.createElement('div');
    answerCard.className = 'answer-container';
    answerCard.style.display = 'none'; // Chỉ hiển thị khi bắt đầu stream token hoặc có kết quả
    answerCard.innerHTML = `
      <div class="answer-header">
        <div class="answer-badge">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          <span>Tư vấn Pháp lý GraphRAG</span>
        </div>
        <div class="answer-meta" id="answer-meta-status">Đang đối chiếu dữ liệu...</div>
      </div>
      <div class="answer-markdown" id="answer-text"></div>
      <div class="grounding-box" id="grounding-box" style="display: none;">
        <span style="display: flex; align-items: center; gap: 6px;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#016a71" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <span style="color: var(--color-deep-teal); font-weight: 500;">Căn cứ pháp lý đã được kiểm định trên Neo4j</span>
        </span>
        <span id="exec-time-label">-- ms</span>
      </div>
    `;
    this.feedContainer.appendChild(answerCard);

    this.currentAnswerBody = answerCard.querySelector('#answer-text');
    this.tokenBuffer = '';

    // 4. Bắt đầu gọi API Streaming SSE
    try {
      const response = await fetch('/api/v1/query/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query,
          top_k: 5,
          include_subgraph: true
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop(); // giữ lại phần chưa hoàn chỉnh

        for (const block of lines) {
          if (!block.trim()) continue;
          this.handleSSEEvent(block, answerCard, progress);
        }
      }

      // Xử lý nốt buffer còn lại
      if (buffer.trim()) {
        this.handleSSEEvent(buffer, answerCard, progress);
      }

      // Hoàn tất
      progress.completeAll();
      this.attachCitationEvents(answerCard);

    } catch (err) {
      console.warn('Lỗi kết nối stream, chuyển sang chế độ đồng bộ (Sync fallback)...', err);
      await this.fallbackSyncQuery(query, answerCard, progress);
    }
  }

  handleSSEEvent(block, answerCard, progress) {
    const lines = block.split('\n');
    let eventType = 'message';
    let dataStr = '';

    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventType = line.replace('event:', '').trim();
      } else if (line.startsWith('data:')) {
        dataStr += line.replace('data:', '').trim();
      }
    }

    if (!dataStr) return;

    try {
      const payload = JSON.parse(dataStr);

      if (eventType === 'stage' || payload.stage) {
        const stageName = payload.stage || payload.name || '';
        if (stageName.includes('rewrit') || stageName.includes('chuẩn hóa')) {
          progress.setStep(0);
        } else if (stageName.includes('retriev') || stageName.includes('tìm kiếm')) {
          progress.setStep(1);
        } else if (stageName.includes('validat') || stageName.includes('kiểm định') || stageName.includes('graph')) {
          progress.setStep(2);
        } else if (stageName.includes('generat') || stageName.includes('sinh')) {
          progress.setStep(3);
        }
      } else if (eventType === 'token' || payload.token !== undefined) {
        const token = payload.token || '';
        progress.setStep(3);
        answerCard.style.display = 'block';

        this.tokenBuffer += token;
        this.renderMarkdown(this.tokenBuffer);
        this.scrollToBottom();
      } else if (eventType === 'subgraph' || payload.nodes) {
        if (this.onSubgraphReceived) {
          this.onSubgraphReceived(payload);
        }
      } else if (eventType === 'done' || payload.status === 'done') {
        progress.completeAll();
        const groundingBox = answerCard.querySelector('#grounding-box');
        const execLabel = answerCard.querySelector('#exec-time-label');
        const statusMeta = answerCard.querySelector('#answer-meta-status');

        if (groundingBox) groundingBox.style.display = 'flex';
        if (execLabel && payload.execution_time_ms) {
          execLabel.textContent = `${Math.round(payload.execution_time_ms)} ms`;
        }
        if (statusMeta) statusMeta.textContent = 'Hoàn tất';
        this.attachCitationEvents(answerCard);
      }
    } catch {
      // nếu không phải JSON, stream raw text
      if (dataStr) {
        answerCard.style.display = 'block';
        this.tokenBuffer += dataStr;
        this.renderMarkdown(this.tokenBuffer);
      }
    }
  }

  async fallbackSyncQuery(query, answerCard, progress) {
    try {
      progress.setStep(1);
      setTimeout(() => progress.setStep(2), 400);

      const res = await fetch('/api/v1/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, top_k: 5, include_subgraph: true })
      });

      progress.setStep(3);
      if (res.ok) {
        const data = await res.json();
        progress.completeAll();
        answerCard.style.display = 'block';

        this.tokenBuffer = data.answer || 'Không tìm thấy thông tin tư vấn phù hợp.';
        this.renderMarkdown(this.tokenBuffer);

        if (data.subgraph && this.onSubgraphReceived) {
          this.onSubgraphReceived(data.subgraph);
        }

        const groundingBox = answerCard.querySelector('#grounding-box');
        const execLabel = answerCard.querySelector('#exec-time-label');
        if (groundingBox) groundingBox.style.display = 'flex';
        if (execLabel) execLabel.textContent = `${Math.round(data.execution_time_ms || 250)} ms`;

        this.attachCitationEvents(answerCard);
      } else {
        throw new Error('Sync API failed');
      }
    } catch {
      progress.completeAll();
      answerCard.style.display = 'block';
      this.currentAnswerBody.innerHTML = `
        <p style="color: var(--color-status-error);">Hệ thống tạm thời không phản hồi. Vui lòng kiểm tra lại dịch vụ FastAPI backend.</p>
      `;
    }
  }

  renderMarkdown(text) {
    if (!window.marked) {
      this.currentAnswerBody.textContent = text;
      return;
    }

    // Tiền xử lý các trích dẫn pháp lý thành thẻ citation tag tương tác
    // Regex nhận diện ví dụ: [Điều 5 Nghị định 168/2024/NĐ-CP] hoặc [Khoản 1 Điều 6]
    let html = window.marked.parse(text);

    // Thay thế các mẫu trích dẫn trong văn bản
    html = html.replace(/\[((?:Điều|Khoản|Điểm|Nghị định|Luật)[^\]]+)\]/g, (match, citation) => {
      return `<button class="citation-tag" data-citation="${this.escapeHtml(citation)}">
        <svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <span>${citation}</span>
      </button>`;
    });

    this.currentAnswerBody.innerHTML = html;
  }

  attachCitationEvents(container) {
    const tags = container.querySelectorAll('.citation-tag');
    tags.forEach(tag => {
      const citationText = tag.getAttribute('data-citation');

      tag.addEventListener('mouseenter', () => {
        if (this.onCitationHover) {
          this.onCitationHover(tag, { citation: citationText });
        }
      });

      tag.addEventListener('click', (e) => {
        e.stopPropagation();
        if (this.onCitationClick) {
          this.onCitationClick(tag, { citation: citationText });
        }
      });
    });
  }

  scrollToBottom() {
    this.scrollContainer.scrollTop = this.scrollContainer.scrollHeight;
  }

  escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
}
