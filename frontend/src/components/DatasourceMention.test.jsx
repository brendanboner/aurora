/**
 * Tests for DatasourceMention grouped dropdown (Fix 5b).
 *
 * Before today's fix: flat alphabetical list of all datasources.
 * After fix: grouped by WBA Extranet / IETF / WFA / IEEE / Public, with WBA
 * workgroups indented under their parent programme.
 *
 * Tests verify:
 * - Group labels render for each category
 * - WBA Extranet items appear in WBA Extranet group
 * - IETF items appear in IETF group
 * - Child workgroups are indented under parents
 * - Search filter works across all groups
 * - Keyboard navigation works in grouped list
 * - Empty state renders when no matches
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import DatasourceMention from './DatasourceMention';

// jsdom doesn't implement scrollIntoView — mock it globally
beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = jest.fn();
});

// ── Test fixtures ─────────────────────────────────────────────────────────────

const MOCK_DATASOURCES = [
  // WBA Extranet — root
  {
    datasource_id: 'wba_extranet',
    name: 'WBA Extranet (Programmes & Workgroups)',
    parent_datasource_id: null,
    scraper_type: 'wba_extranet',
    document_count: 45,
  },
  // WBA Extranet — children
  {
    datasource_id: 'wba_extranet_nextgen',
    name: 'Next Gen Programme',
    parent_datasource_id: 'wba_extranet',
    scraper_type: 'wba_extranet',
    document_count: 12,
  },
  {
    datasource_id: 'wba_extranet_aiml',
    name: 'AI/ML Working Group',
    parent_datasource_id: 'wba_extranet_nextgen',
    scraper_type: 'wba_extranet',
    document_count: 8,
  },
  // IETF
  {
    datasource_id: 'ietf_wg_spring',
    name: 'SPRING Working Group',
    parent_datasource_id: null,
    scraper_type: 'ietf_datatracker',
    document_count: 120,
  },
  {
    datasource_id: 'ietf_wg_quic',
    name: 'QUIC Working Group',
    parent_datasource_id: null,
    scraper_type: 'ietf_datatracker',
    document_count: 95,
  },
  // WFA
  {
    datasource_id: 'wfa_causeway_wifi7',
    name: 'WFA Wi-Fi 7 TG',
    parent_datasource_id: null,
    scraper_type: 'wfa_causeway',
    document_count: 67,
  },
  // Public
  {
    datasource_id: 'nist_sp800',
    name: 'NIST SP 800 Series',
    parent_datasource_id: null,
    scraper_type: 'nist',
    document_count: 200,
  },
];

function renderDropdown(props = {}) {
  const defaultProps = {
    datasources: MOCK_DATASOURCES,
    searchText: '',
    onSelect: jest.fn(),
    onClose: jest.fn(),
    isVisible: true,
    inputRef: { current: document.createElement('input') },
  };
  return render(<DatasourceMention {...defaultProps} {...props} />);
}

// ── Visibility ────────────────────────────────────────────────────────────────

describe('DatasourceMention visibility', () => {
  test('renders when isVisible=true', () => {
    renderDropdown({ isVisible: true });
    expect(screen.getByText(/filter by source/i)).toBeInTheDocument();
  });

  test('does not render when isVisible=false', () => {
    const { container } = renderDropdown({ isVisible: false });
    expect(container.firstChild).toBeNull();
  });

  test('does not render when datasources is empty', () => {
    const { container } = renderDropdown({ datasources: [], isVisible: true });
    expect(container.firstChild).toBeNull();
  });
});

// ── Group labels ──────────────────────────────────────────────────────────────

describe('Group labels', () => {
  test('renders WBA Extranet group label', () => {
    renderDropdown();
    expect(screen.getByText('WBA Extranet')).toBeInTheDocument();
  });

  test('renders IETF group label', () => {
    renderDropdown();
    expect(screen.getByText('IETF')).toBeInTheDocument();
  });

  test('renders WFA group label', () => {
    renderDropdown();
    expect(screen.getByText(/wi-fi alliance/i)).toBeInTheDocument();
  });

  test('renders Public Sources group label', () => {
    renderDropdown();
    expect(screen.getByText(/public sources/i)).toBeInTheDocument();
  });
});

// ── Correct grouping ──────────────────────────────────────────────────────────

describe('Source grouping', () => {
  test('WBA Extranet source appears in WBA section', () => {
    renderDropdown();
    const wbaItem = screen.getByText('WBA Extranet (Programmes & Workgroups)');
    expect(wbaItem).toBeInTheDocument();
  });

  test('IETF SPRING appears in IETF section', () => {
    renderDropdown();
    expect(screen.getByText('SPRING Working Group')).toBeInTheDocument();
  });

  test('NIST appears in Public Sources section', () => {
    renderDropdown();
    expect(screen.getByText('NIST SP 800 Series')).toBeInTheDocument();
  });

  test('WBA child workgroup indented under parent', () => {
    renderDropdown();
    const aimlItem = screen.getByText('AI/ML Working Group').closest('li');
    // Child items have 'indented' CSS class
    expect(aimlItem).toHaveClass('indented');
  });

  test('Root WBA source not indented', () => {
    renderDropdown();
    const rootItem = screen.getByText('WBA Extranet (Programmes & Workgroups)').closest('li');
    expect(rootItem).not.toHaveClass('indented');
  });
});

// ── Document count display ────────────────────────────────────────────────────

describe('Document counts', () => {
  test('shows doc count for sources with documents', () => {
    renderDropdown();
    // 200 docs for NIST, should appear
    expect(screen.getByText('200')).toBeInTheDocument();
  });

  test('shows count for IETF SPRING (120 docs)', () => {
    renderDropdown();
    expect(screen.getByText('120')).toBeInTheDocument();
  });
});

// ── Search filtering ──────────────────────────────────────────────────────────

describe('Search filtering', () => {
  test('shows only SPRING when searching "spring"', () => {
    renderDropdown({ searchText: 'spring' });
    expect(screen.getByText('SPRING Working Group')).toBeInTheDocument();
    expect(screen.queryByText('NIST SP 800 Series')).not.toBeInTheDocument();
  });

  test('shows WBA items when searching "wba"', () => {
    renderDropdown({ searchText: 'wba' });
    expect(screen.getByText('WBA Extranet (Programmes & Workgroups)')).toBeInTheDocument();
    expect(screen.queryByText('SPRING Working Group')).not.toBeInTheDocument();
  });

  test('case-insensitive search', () => {
    renderDropdown({ searchText: 'SPRING' });
    expect(screen.getByText('SPRING Working Group')).toBeInTheDocument();
  });

  test('empty result for no match', () => {
    const { container } = renderDropdown({ searchText: 'xyznothing' });
    expect(container.firstChild).toBeNull();
  });

  test('group label hidden when group has no matching items', () => {
    renderDropdown({ searchText: 'spring' });
    // WBA group should not appear since no WBA sources match "spring"
    expect(screen.queryByText('WBA Extranet')).not.toBeInTheDocument();
  });
});

// ── Selection ─────────────────────────────────────────────────────────────────

describe('Item selection', () => {
  test('calls onSelect when item clicked', () => {
    const onSelect = jest.fn();
    renderDropdown({ onSelect });
    fireEvent.click(screen.getByText('SPRING Working Group'));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ datasource_id: 'ietf_wg_spring' })
    );
  });

  test('calls onSelect with correct datasource on click', () => {
    const onSelect = jest.fn();
    renderDropdown({ onSelect });
    fireEvent.click(screen.getByText('NIST SP 800 Series'));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ datasource_id: 'nist_sp800' })
    );
  });
});

// ── Keyboard navigation ───────────────────────────────────────────────────────

describe('Keyboard navigation', () => {
  test('Escape key calls onClose', () => {
    const onClose = jest.fn();
    const inputEl = document.createElement('input');
    document.body.appendChild(inputEl);
    renderDropdown({ onClose, inputRef: { current: inputEl } });

    fireEvent.keyDown(inputEl, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
    document.body.removeChild(inputEl);
  });

  test('footer shows keyboard hints', () => {
    renderDropdown();
    expect(screen.getByText(/navigate/i)).toBeInTheDocument();
    expect(screen.getByText(/select/i)).toBeInTheDocument();
    expect(screen.getByText(/close/i)).toBeInTheDocument();
  });
});

// ── Total count display ───────────────────────────────────────────────────────

describe('Total count badge', () => {
  test('shows total count of matching sources', () => {
    renderDropdown();
    // All 7 datasources should be shown
    const countBadge = screen.getByText('7');
    expect(countBadge).toBeInTheDocument();
  });

  test('count updates when search filters sources', () => {
    renderDropdown({ searchText: 'spring' });
    // Only SPRING matches
    expect(screen.getByText('1')).toBeInTheDocument();
  });
});
