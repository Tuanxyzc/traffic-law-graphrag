/**
 * Master Application Entrypoint
 * Traffic Law GraphRAG UI
 */

import { SidebarManager } from './sidebar.js';
import { SearchManager } from './search_hero.js';
import { ChatFeedManager } from './chat_feed.js';
import { CitationPopoverManager } from './citation_popover.js';
import { GraphViewer } from './graph_viewer.js';
import { DocumentBrowserManager } from './document_browser.js';

document.addEventListener('DOMContentLoaded', () => {
  // 1. Initialize Lucide Icons
  if (window.lucide) {
    window.lucide.createIcons();
  }

  // 2. Initialize Knowledge Graph Viewer (Collapsible Panel)
  const graphViewer = new GraphViewer({
    onSelectNode: (nodeData) => {
      console.log('Selected node on graph:', nodeData);
    }
  });

  // 3. Initialize Citation Popover Manager
  const popoverManager = new CitationPopoverManager({
    onFocusGraph: (unitId) => {
      graphViewer.focusNode(unitId);
    }
  });

  // 4. Initialize Chat Feed & Streaming Manager
  const chatFeed = new ChatFeedManager({
    onSubgraphReceived: (subgraphData) => {
      graphViewer.renderSubGraph(subgraphData);
    },
    onCitationHover: (targetEl, citationData) => {
      popoverManager.show(targetEl, citationData);
    },
    onCitationClick: (targetEl, citationData) => {
      popoverManager.show(targetEl, citationData);
    }
  });

  // 5. Initialize Document Browser View
  const docBrowser = new DocumentBrowserManager({
    onSelectDocument: (docId) => {
      sidebarManager.setActiveNav('chat');
      docBrowser.hide();
      searchManager.setHeroQuery(`Quy định chi tiết trong văn bản ${docId}`);
    }
  });

  // 6. Initialize Search Hero & Controls
  const searchManager = new SearchManager({
    onSubmitQuery: (query) => {
      sidebarManager.saveQuery(query);
      searchManager.hideHero();
      chatFeed.sendQuery(query);
      if (window.lucide) window.lucide.createIcons();
    }
  });

  // 7. Initialize Sidebar Navigation
  const sidebarManager = new SidebarManager({
    onSelectHistory: (query) => {
      sidebarManager.setActiveNav('chat');
      docBrowser.hide();
      searchManager.hideHero();
      chatFeed.sendQuery(query);
      if (window.lucide) window.lucide.createIcons();
    },
    onNewChat: () => {
      docBrowser.hide();
      chatFeed.clear();
      searchManager.showHero();
    },
    onSwitchView: (viewName) => {
      if (viewName === 'docs') {
        docBrowser.show();
      } else {
        docBrowser.hide();
      }
    }
  });
});
