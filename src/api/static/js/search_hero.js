/**
 * Search Hero & Input Controls
 */

export class SearchManager {
  constructor({ onSubmitQuery }) {
    this.onSubmitQuery = onSubmitQuery;

    this.heroSection = document.getElementById('hero-section');
    this.heroInput = document.getElementById('hero-query-input');
    this.heroSubmitBtn = document.getElementById('hero-submit-btn');

    this.stickyFooter = document.getElementById('sticky-footer-search');
    this.footerInput = document.getElementById('footer-query-input');
    this.footerSubmitBtn = document.getElementById('footer-submit-btn');

    this.suggestionChips = document.querySelectorAll('.suggestion-chip');

    this.initEvents();
  }

  initEvents() {
    // Hero input handling
    this.heroInput.addEventListener('input', () => {
      this.autoResize(this.heroInput);
      const hasText = this.heroInput.value.trim().length > 1;
      this.heroSubmitBtn.disabled = !hasText;
    });

    this.heroInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.submitHero();
      }
    });

    this.heroSubmitBtn.addEventListener('click', () => {
      this.submitHero();
    });

    // Sticky footer input handling
    this.footerInput.addEventListener('input', () => {
      this.autoResize(this.footerInput);
      const hasText = this.footerInput.value.trim().length > 1;
      this.footerSubmitBtn.disabled = !hasText;
    });

    this.footerInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.submitFooter();
      }
    });

    this.footerSubmitBtn.addEventListener('click', () => {
      this.submitFooter();
    });

    // Suggestion chips
    this.suggestionChips.forEach(chip => {
      chip.addEventListener('click', () => {
        const query = chip.getAttribute('data-query');
        if (query) {
          this.setHeroQuery(query);
          this.submitHero();
        }
      });
    });
  }

  autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
  }

  setHeroQuery(query) {
    this.heroInput.value = query;
    this.autoResize(this.heroInput);
    this.heroSubmitBtn.disabled = false;
  }

  submitHero() {
    const query = this.heroInput.value.trim();
    if (query.length > 1 && this.onSubmitQuery) {
      this.onSubmitQuery(query);
      this.heroInput.value = '';
      this.heroSubmitBtn.disabled = true;
    }
  }

  submitFooter() {
    const query = this.footerInput.value.trim();
    if (query.length > 1 && this.onSubmitQuery) {
      this.onSubmitQuery(query);
      this.footerInput.value = '';
      this.footerSubmitBtn.disabled = true;
    }
  }

  showHero() {
    this.heroSection.style.display = 'flex';
    this.stickyFooter.style.display = 'none';
  }

  hideHero() {
    this.heroSection.style.display = 'none';
    this.stickyFooter.style.display = 'block';
  }
}
