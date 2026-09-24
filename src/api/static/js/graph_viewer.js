/**
 * Knowledge Graph Viewer (Cytoscape.js integration)
 */

export class GraphViewer {
  constructor({ onSelectNode }) {
    this.onSelectNode = onSelectNode;
    this.panel = document.getElementById('graph-panel');
    this.toggleBtn = document.getElementById('btn-toggle-graph');
    this.closeBtn = document.getElementById('btn-close-graph');
    this.arrowIcon = document.getElementById('graph-arrow-icon');
    this.cyContainer = document.getElementById('cy-graph');

    this.cy = null;
    this.isExpanded = false;

    this.initEvents();
    this.initCytoscape();
  }

  initEvents() {
    this.toggleBtn.addEventListener('click', () => {
      this.toggle();
    });

    this.closeBtn.addEventListener('click', () => {
      this.collapse();
    });
  }

  toggle() {
    if (this.isExpanded) {
      this.collapse();
    } else {
      this.expand();
    }
  }

  expand() {
    this.isExpanded = true;
    this.panel.classList.remove('collapsed');
    this.toggleBtn.classList.add('active');
    this.arrowIcon.setAttribute('data-lucide', 'chevron-left');
    lucide.createIcons();

    setTimeout(() => {
      if (this.cy) {
        this.cy.resize();
        this.cy.fit(null, 30);
      }
    }, 280);
  }

  collapse() {
    this.isExpanded = false;
    this.panel.classList.add('collapsed');
    this.toggleBtn.classList.remove('active');
    this.arrowIcon.setAttribute('data-lucide', 'chevron-right');
    lucide.createIcons();
  }

  initCytoscape() {
    if (!window.cytoscape) return;

    this.cy = window.cytoscape({
      container: this.cyContainer,
      style: [
        {
          selector: 'node',
          style: {
            'label': 'data(label)',
            'font-family': 'Inter, sans-serif',
            'font-size': '10px',
            'text-valign': 'center',
            'text-halign': 'center',
            'color': '#ffffff',
            'text-wrap': 'wrap',
            'text-max-width': '80px',
            'border-width': 1.5,
            'border-color': '#ffffff',
            'transition-property': 'background-color, border-color, width, height',
            'transition-duration': '0.2s'
          }
        },
        {
          selector: 'node[type = "Document"]',
          style: {
            'background-color': '#016a71',
            'shape': 'round-rectangle',
            'width': '85px',
            'height': '36px',
            'font-size': '11px',
            'font-weight': 500
          }
        },
        {
          selector: 'node[type = "Article"]',
          style: {
            'background-color': '#2563eb',
            'shape': 'round-rectangle',
            'width': '75px',
            'height': '32px'
          }
        },
        {
          selector: 'node[type = "Clause"], node[type = "Point"]',
          style: {
            'background-color': '#4b5563',
            'shape': 'ellipse',
            'width': '40px',
            'height': '40px'
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-color': '#27251e',
            'border-width': 3,
            'shadow-blur': 12,
            'shadow-color': 'rgba(1, 106, 113, 0.4)'
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 1.5,
            'line-color': '#9ca3af',
            'target-arrow-color': '#9ca3af',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'font-size': '8px',
            'font-family': 'Inter, sans-serif',
            'color': '#6b7280',
            'label': 'data(label)',
            'text-rotation': 'autorotate',
            'text-margin-y': -8
          }
        },
        {
          selector: 'edge[type = "AMENDS"]',
          style: {
            'line-color': '#dc2626',
            'target-arrow-color': '#dc2626',
            'line-style': 'dashed',
            'width': 2
          }
        },
        {
          selector: 'edge[type = "THAM_CHIEU"]',
          style: {
            'line-color': '#2563eb',
            'target-arrow-color': '#2563eb'
          }
        }
      ],
      layout: {
        name: 'cose',
        animate: false,
        padding: 24,
        nodeRepulsion: 4500,
        idealEdgeLength: 60
      }
    });

    this.cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      if (this.onSelectNode) {
        this.onSelectNode(node.data());
      }
    });
  }

  renderSubGraph(subgraphData) {
    if (!this.cy || !subgraphData) return;

    this.cy.elements().remove();

    const elements = [];

    // Parse nodes
    if (Array.isArray(subgraphData.nodes)) {
      subgraphData.nodes.forEach(node => {
        elements.push({
          group: 'nodes',
          data: {
            id: node.id,
            label: node.properties?.title || node.properties?.canonical_id || node.label || node.id,
            type: node.label || 'Clause',
            properties: node.properties || {}
          }
        });
      });
    }

    // Parse edges
    if (Array.isArray(subgraphData.relationships)) {
      subgraphData.relationships.forEach((rel, idx) => {
        elements.push({
          group: 'edges',
          data: {
            id: `edge-${idx}`,
            source: rel.source,
            target: rel.target,
            label: rel.type || '',
            type: rel.type || 'RELATION'
          }
        });
      });
    }

    if (elements.length > 0) {
      this.cy.add(elements);
      this.cy.layout({
        name: 'cose',
        animate: true,
        animationDuration: 400,
        padding: 30,
        nodeRepulsion: 5000,
        idealEdgeLength: 70
      }).run();
    }
  }

  focusNode(nodeId) {
    if (!this.cy) return;
    this.expand();

    const targetNode = this.cy.getElementById(nodeId);
    if (targetNode && targetNode.length > 0) {
      this.cy.elements().unselect();
      targetNode.select();
      this.cy.animate({
        center: { eles: targetNode },
        zoom: 1.4,
        duration: 350
      });
    }
  }
}
