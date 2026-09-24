/**
 * Citation Popover Management
 */

export class CitationPopoverManager {
  constructor({ onFocusGraph }) {
    this.onFocusGraph = onFocusGraph;
    this.popover = document.getElementById('citation-popover');
    this.titleEl = document.getElementById('popover-title');
    this.statusEl = document.getElementById('popover-status');
    this.contentEl = document.getElementById('popover-content');
    this.graphBtn = document.getElementById('popover-graph-btn');

    this.activeUnitId = null;
    this.hideTimeout = null;

    this.initEvents();
  }

  initEvents() {
    // Hover on popover keeps it open
    this.popover.addEventListener('mouseenter', () => {
      clearTimeout(this.hideTimeout);
    });

    this.popover.addEventListener('mouseleave', () => {
      this.hide();
    });

    // Click outside hides popover
    document.addEventListener('click', (e) => {
      if (!this.popover.contains(e.target) && !e.target.closest('.citation-tag')) {
        this.hide();
      }
    });

    this.graphBtn.addEventListener('click', () => {
      if (this.onFocusGraph && this.activeUnitId) {
        this.onFocusGraph(this.activeUnitId);
        this.hide();
      }
    });
  }

  show(targetElement, citationData) {
    clearTimeout(this.hideTimeout);
    this.activeUnitId = citationData.unitId || citationData.citation;

    this.titleEl.textContent = citationData.citation || 'Căn cứ pháp luật';

    // Status: Đang có hiệu lực hoặc Đã sửa đổi
    const isValid = citationData.isValid !== false;
    this.statusEl.textContent = isValid ? 'Đang có hiệu lực' : 'Đã sửa đổi';
    this.statusEl.className = isValid ? 'popover-badge valid' : 'popover-badge amended';

    this.contentEl.textContent = citationData.text || 'Đang tra cứu cơ sở dữ liệu pháp luật...';

    // Calculate position
    const rect = targetElement.getBoundingClientRect();
    const popoverWidth = 320;
    let left = rect.left + window.scrollX;
    let top = rect.bottom + window.scrollY + 8;

    // Prevent overflow right
    if (left + popoverWidth > window.innerWidth - 20) {
      left = window.innerWidth - popoverWidth - 20;
    }

    this.popover.style.left = `${left}px`;
    this.popover.style.top = `${top}px`;
    this.popover.style.display = 'block';

    // Fetch details if available from API
    if (citationData.unitId) {
      this.fetchProvisionDetail(citationData.unitId);
    }
  }

  async fetchProvisionDetail(unitId) {
    try {
      const res = await fetch(`/api/v1/graph/provisions/${encodeURIComponent(unitId)}`);
      if (res.ok) {
        const data = await res.json();
        this.titleEl.textContent = `${data.document_id} — ${data.title || data.unit_id}`;
        this.contentEl.textContent = data.content || 'Nội dung điều khoản pháp luật.';
        const isValid = data.is_valid !== false;
        this.statusEl.textContent = isValid ? 'Đang có hiệu lực' : 'Đã sửa đổi';
        this.statusEl.className = isValid ? 'popover-badge valid' : 'popover-badge amended';
      }
    } catch {
      // Giữ nội dung tóm lược hiện có
    }
  }

  scheduleHide() {
    this.hideTimeout = setTimeout(() => {
      this.hide();
    }, 300);
  }

  hide() {
    this.popover.style.display = 'none';
  }
}
