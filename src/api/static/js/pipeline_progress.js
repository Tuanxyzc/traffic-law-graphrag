/**
 * Pipeline Progress Component
 * Dynamically visualizes the JurisGraph-VN 2-Tier Query Router & Execution Path:
 * - Direct Lookup (Fast-Path): Bypasses Hybrid Retrieval -> Direct Neo4j Node Lookup -> Answer Generation
 * - Hybrid Search: Query Rewriting -> BM25 + Vector Retrieval -> Neo4j Graph Validation -> Answer Generation
 */

export class PipelineProgress {
  constructor() {
    this.container = null;
    this.routingDecision = null; // { action, unit_id, reason, extracted_by }
    this.isBypassed = false;

    // Initial candidate steps before routing decision is made
    this.steps = [
      {
        id: 'routing',
        label: 'Phân luồng & Bóc tách tọa độ pháp lý',
        detail: 'Đang quét số hiệu Điều, Khoản, Điểm và tên văn bản...',
        status: 'active'
      },
      {
        id: 'retrieve',
        label: 'Tìm kiếm dữ liệu pháp lý',
        detail: 'Chờ kết quả phân luồng truy vấn...',
        status: 'pending'
      },
      {
        id: 'graph',
        label: 'Kiểm định đồ thị Neo4j',
        detail: 'Đối chiếu hiệu lực văn bản và liên kết chế tài',
        status: 'pending'
      },
      {
        id: 'generate',
        label: 'Tổng hợp văn bản tư vấn',
        detail: 'Sinh câu trả lời kèm căn cứ pháp lý đã kiểm chứng',
        status: 'pending'
      }
    ];
  }

  createDOM() {
    const card = document.createElement('div');
    card.className = 'pipeline-progress-card';

    // Header
    const header = document.createElement('div');
    header.className = 'pipeline-header';
    header.id = 'pipeline-header';
    header.innerHTML = `
      <div style="display: flex; align-items: center; gap: 6px;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
        </svg>
        <span>Tiến trình phân tích pháp lý</span>
      </div>
      <span class="pipeline-mode-pill pending" id="pipeline-mode-pill">
        Đang định tuyến...
      </span>
    `;
    card.appendChild(header);

    // Dynamic Router Decision Callout Container
    const routerCardWrap = document.createElement('div');
    routerCardWrap.id = 'router-decision-container';
    card.appendChild(routerCardWrap);

    // Steps list
    const stepsList = document.createElement('div');
    stepsList.className = 'pipeline-steps';
    stepsList.id = 'pipeline-steps-list';
    card.appendChild(stepsList);

    this.container = card;
    this.renderSteps();

    return card;
  }

  /**
   * Updates routing decision and dynamically morphs pipeline steps based on DIRECT_LOOKUP vs HYBRID_SEARCH
   */
  setRoutingDecision(data) {
    if (!data) return;
    const action = (data.action || data.routing_action || '').toUpperCase();
    const unitId = data.unit_id || data.matched_unit_id || null;
    const reason = data.reason || null;
    const extractedBy = data.extracted_by || null;

    this.routingDecision = { action, unitId, reason, extractedBy };

    const modePill = this.container.querySelector('#pipeline-mode-pill');
    const decisionContainer = this.container.querySelector('#router-decision-container');

    if (action === 'DIRECT_LOOKUP') {
      this.isBypassed = true;
      if (modePill) {
        modePill.className = 'pipeline-mode-pill direct';
        modePill.innerHTML = `
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
          </svg>
          <span>Fast-Path (Direct Lookup)</span>
        `;
      }

      if (decisionContainer) {
        decisionContainer.innerHTML = `
          <div class="router-decision-card direct">
            <div class="router-card-badge-row">
              <span class="router-chip chip-direct">⚡ FAST-PATH</span>
              ${unitId ? `<span class="router-unit-id-tag">Mã định danh: <code>${this.escapeHtml(unitId)}</code></span>` : ''}
              ${extractedBy ? `<span class="router-source-tag">${extractedBy === 'tier1_regex' ? 'Tier 1 Regex' : 'Tier 2 LLM'}</span>` : ''}
            </div>
            <div class="router-card-desc">
              Phát hiện số hiệu điều khoản cụ thể. Hệ thống kích hoạt <strong>Tra cứu định danh (Fast-Path)</strong>: bỏ qua tìm kiếm lai để truy xuất trực tiếp cây phân cấp & chế tài trên Neo4j.
            </div>
          </div>
        `;
      }

      // Configure steps for DIRECT_LOOKUP
      this.steps = [
        {
          id: 'routing',
          label: 'Phân luồng: Tra cứu định danh (Direct Lookup)',
          badge: 'Fast-Path',
          badgeClass: 'fastpath',
          detail: unitId ? `Đã xác định tọa độ: ${unitId}` : 'Đã bóc tách tọa độ pháp lý',
          status: 'done'
        },
        {
          id: 'retrieve',
          label: 'Tìm kiếm lai (Dense Vector & BM25)',
          badge: 'Bỏ qua (Fast-path)',
          badgeClass: 'skipped',
          detail: 'Bỏ qua tìm kiếm vector vì đã có mã điều khoản chính xác',
          status: 'skipped'
        },
        {
          id: 'graph',
          label: 'Tra cứu trực tiếp Node & Chế tài trên Neo4j',
          detail: unitId ? `Trích xuất node ${unitId}, kiểm tra hiệu lực & quan hệ chế tài` : 'Kiểm tra hiệu lực pháp luật trên Neo4j',
          status: 'active'
        },
        {
          id: 'generate',
          label: 'Tổng hợp văn bản tư vấn pháp lý',
          detail: 'Sinh câu trả lời kèm căn cứ pháp lý đã kiểm chứng',
          status: 'pending'
        }
      ];

    } else {
      // HYBRID_SEARCH
      this.isBypassed = false;
      if (modePill) {
        modePill.className = 'pipeline-mode-pill hybrid';
        modePill.innerHTML = `
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>
          </svg>
          <span>Hybrid GraphRAG</span>
        `;
      }

      if (decisionContainer) {
        decisionContainer.innerHTML = `
          <div class="router-decision-card hybrid">
            <div class="router-card-badge-row">
              <span class="router-chip chip-hybrid">🔍 HYBRID SEARCH</span>
              <span class="router-unit-id-tag">Tìm kiếm ngữ nghĩa đa nguồn</span>
              ${extractedBy ? `<span class="router-source-tag">${extractedBy === 'tier1_regex' ? 'Tier 1 Regex' : 'Tier 2 LLM'}</span>` : ''}
            </div>
            <div class="router-card-desc">
              ${this.escapeHtml(reason || 'Câu hỏi tình huống/hành vi vi phạm. Hệ thống kích hoạt chuẩn hóa truy vấn, tìm kiếm lai đa nguồn và kiểm định trên đồ thị Neo4j.')}
            </div>
          </div>
        `;
      }

      // Configure steps for HYBRID_SEARCH
      this.steps = [
        {
          id: 'routing',
          label: 'Phân luồng: Tìm kiếm ngữ nghĩa lai (Hybrid Search)',
          badge: 'Semantic',
          detail: 'Câu hỏi hành vi/mức phạt, phân tích ngữ nghĩa trên toàn bộ văn bản',
          status: 'done'
        },
        {
          id: 'rewrite',
          label: 'Chuẩn hóa câu hỏi & Phân tích ý định',
          detail: 'Chuẩn hóa thuật ngữ pháp lý và trích xuất thực thể phương tiện',
          status: 'active'
        },
        {
          id: 'retrieve',
          label: 'Tìm kiếm lai đa nguồn (Dense Vector + BM25 RRF)',
          detail: 'Truy xuất các đoạn văn bản pháp lý phù hợp nhất qua rank fusion',
          status: 'pending'
        },
        {
          id: 'graph',
          label: 'Kiểm định đồ thị Neo4j',
          detail: 'Xác thực hiệu lực hiện hành và điều khoản sửa đổi, bổ sung',
          status: 'pending'
        },
        {
          id: 'generate',
          label: 'Tổng hợp văn bản tư vấn',
          detail: 'Sinh câu trả lời kèm căn cứ pháp lý đã kiểm chứng',
          status: 'pending'
        }
      ];
    }

    this.renderSteps();
  }

  setStepById(stepId, status = 'active', customDetail = null) {
    let found = false;
    this.steps.forEach((step) => {
      if (step.id === stepId) {
        step.status = status;
        if (customDetail) step.detail = customDetail;
        found = true;
      } else if (!found && step.status !== 'skipped') {
        step.status = 'done';
      }
    });

    this.renderSteps();
  }

  /** Backward compatibility with numeric indices */
  setStep(index) {
    if (this.steps[index]) {
      this.setStepById(this.steps[index].id, 'active');
    }
  }

  completeAll() {
    this.steps.forEach((step) => {
      if (step.status !== 'skipped') {
        step.status = 'done';
      }
    });

    const modePill = this.container.querySelector('#pipeline-mode-pill');
    if (modePill) {
      if (this.routingDecision?.action === 'DIRECT_LOOKUP') {
        modePill.className = 'pipeline-mode-pill direct';
      } else {
        modePill.className = 'pipeline-mode-pill done';
      }
    }

    this.renderSteps();
  }

  renderSteps() {
    if (!this.container) return;
    const stepsList = this.container.querySelector('#pipeline-steps-list');
    if (!stepsList) return;

    stepsList.innerHTML = '';

    this.steps.forEach((step) => {
      const item = document.createElement('div');
      item.className = `pipeline-step-item ${step.status}`;
      item.id = `step-item-${step.id}`;

      let iconHtml = '';
      if (step.status === 'done') {
        iconHtml = `
          <svg class="done-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 6L9 17l-5-5"/>
          </svg>
        `;
      } else if (step.status === 'active') {
        iconHtml = `
          <svg class="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
          </svg>
        `;
      } else if (step.status === 'skipped') {
        iconHtml = `
          <svg class="skip-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 19 22 12 13 5 13 19"/>
            <polygon points="2 19 11 12 2 5 2 19"/>
          </svg>
        `;
      } else {
        iconHtml = '<span class="pending-dot"></span>';
      }

      item.innerHTML = `
        <div class="step-icon-wrap">${iconHtml}</div>
        <div class="step-content-wrap">
          <div class="step-title-row">
            <span class="step-title">${step.label}</span>
            ${step.badge ? `<span class="step-badge ${step.badgeClass || ''}">${step.badge}</span>` : ''}
          </div>
          ${step.detail ? `<span class="step-detail">${this.escapeHtml(step.detail)}</span>` : ''}
        </div>
      `;

      stepsList.appendChild(item);
    });
  }

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}
