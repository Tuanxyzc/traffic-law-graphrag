/**
 * Pipeline Progress Component (4-Step SSE Stages)
 * 1. Chuẩn hóa câu hỏi
 * 2. Tìm kiếm lai
 * 3. Kiểm định đồ thị Neo4j
 * 4. Sinh câu trả lời
 */

export class PipelineProgress {
  constructor() {
    this.container = null;
    this.steps = [
      { id: 'rewrite', label: 'Chuẩn hóa câu hỏi' },
      { id: 'retrieve', label: 'Tìm kiếm lai' },
      { id: 'graph', label: 'Kiểm định đồ thị Neo4j' },
      { id: 'generate', label: 'Sinh câu trả lời' }
    ];
    this.currentStepIndex = 0;
  }

  createDOM() {
    const card = document.createElement('div');
    card.className = 'pipeline-progress-card';

    const header = document.createElement('div');
    header.className = 'pipeline-header';
    header.innerHTML = `
      <span>Tiến trình phân tích pháp lý</span>
      <span style="font-size: 11px; text-transform: none; color: var(--color-deep-teal);">GraphRAG Active</span>
    `;
    card.appendChild(header);

    const stepsList = document.createElement('div');
    stepsList.className = 'pipeline-steps';

    this.steps.forEach((step, idx) => {
      const stepItem = document.createElement('div');
      stepItem.className = 'pipeline-step-item';
      stepItem.id = `step-item-${idx}`;

      const iconWrap = document.createElement('div');
      iconWrap.className = 'step-icon-wrap';
      iconWrap.id = `step-icon-${idx}`;
      iconWrap.innerHTML = '<span class="pending-dot"></span>';

      const labelSpan = document.createElement('span');
      labelSpan.id = `step-label-${idx}`;
      labelSpan.textContent = step.label;

      stepItem.appendChild(iconWrap);
      stepItem.appendChild(labelSpan);
      stepsList.appendChild(stepItem);
    });

    card.appendChild(stepsList);
    this.container = card;
    return card;
  }

  setStep(index) {
    this.currentStepIndex = index;

    this.steps.forEach((_, idx) => {
      const item = this.container.querySelector(`#step-item-${idx}`);
      const iconWrap = this.container.querySelector(`#step-icon-${idx}`);

      if (!item || !iconWrap) return;

      if (idx < index) {
        // Đã hoàn thành (Done)
        item.className = 'pipeline-step-item done';
        iconWrap.innerHTML = `
          <svg class="done-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 6L9 17l-5-5"/>
          </svg>
        `;
      } else if (idx === index) {
        // Đang chạy (Loading spinner xoay vòng)
        item.className = 'pipeline-step-item active';
        iconWrap.innerHTML = `
          <svg class="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
          </svg>
        `;
      } else {
        // Chưa tới lượt (Pending)
        item.className = 'pipeline-step-item';
        iconWrap.innerHTML = '<span class="pending-dot"></span>';
      }
    });
  }

  completeAll() {
    this.steps.forEach((_, idx) => {
      const item = this.container.querySelector(`#step-item-${idx}`);
      const iconWrap = this.container.querySelector(`#step-icon-${idx}`);
      if (item && iconWrap) {
        item.className = 'pipeline-step-item done';
        iconWrap.innerHTML = `
          <svg class="done-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 6L9 17l-5-5"/>
          </svg>
        `;
      }
    });
  }
}
