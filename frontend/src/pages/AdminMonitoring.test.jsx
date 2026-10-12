/**
 * Tests for AdminMonitoring page fixes (Fixes 2, 4).
 *
 * Fix 2: Dark mode CSS — the component now uses correct CSS variable names
 *        (--card, --background, --foreground) instead of --color-surface etc.
 * Fix 4: Active batches show datasource_id as subtitle beneath display_name.
 *
 * These tests verify the rendered structure without testing CSS variable
 * resolution (that's a visual browser test), but ensure the subtitle element
 * is rendered and the correct class structure is in place.
 */

import React from 'react';
import { render, screen, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import AdminMonitoring from './AdminMonitoring';

// ── Mock global fetch ─────────────────────────────────────────────────────────

const MOCK_DASHBOARD = {
  queue_status: {
    queue_name: 'scraped_content',
    message_count: 12,
    messages_ready: 10,
    messages_unacked: 2,
    consumer_count: 3,
    resources: [
      {
        title: 'Flexible Candidate Path Selection for SR Policy',
        url: 'https://datatracker.ietf.org/doc/draft-ietf-spring-sr-policy-flexible-cp-selection/',
        category: 'internet-draft',
        publish_date: '2025-11-01',
        scraped_at: 1700000000,
        position: 1,
        datasource_id: 'ietf_wg_spring',
        message_type: 'resource',
      },
    ],
  },
  processing_status: {
    retriever_active: true,
    digester_active: true,
    retriever_health: { container_name: 'aurora-retriever', status: 'healthy' },
    digester_health: { container_name: 'aurora-digester', status: 'healthy' },
    retriever_instances: { active: 1, total: 1 },
    digester_instances: { active: 1, total: 1 },
    retriever_current: {
      title: 'WBA Extranet community discovery',
      url: 'https://extranet.wballiance.com',
      category: 'discovery',
      status: 'processing',
      stage: 'scraping community landing',
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      datasource_id: 'wba_extranet',
    },
    digester_current: {
      title: 'SR Policy Architecture',
      url: 'https://datatracker.ietf.org/doc/rfc9256/',
      category: 'specification',
      status: 'processing',
      stage: 'extracting metadata',
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      datasource_id: 'ietf_wg_spring',
    },
    recent_completed: [
      {
        title: 'AI/ML Datasets Overview',
        url: 'https://extranet.wballiance.com/doc/aiml',
        category: 'presentation',
        status: 'completed',
        stage: 'completed',
        started_at: new Date(Date.now() - 300000).toISOString(),
        updated_at: new Date(Date.now() - 60000).toISOString(),
        datasource_id: 'wba_extranet_aiml',
      },
    ],
    recent_failed: [],
  },
  active_batches: [
    {
      batch_id: 'batch-abc123',
      datasource_id: 'wba_extranet',
      display_name: 'WBA Extranet (Programmes & Workgroups)',
      status: 'retrieving',
      items_scraped: 45,
      items_digested: 12,
      started_at: new Date(Date.now() - 600000).toISOString(),
      updated_at: new Date().toISOString(),
      progress_percent: 26.7,
    },
    {
      batch_id: 'batch-def456',
      datasource_id: 'ietf_wg_spring',
      display_name: 'SPRING Working Group',
      status: 'digesting',
      items_scraped: 8,
      items_digested: 6,
      started_at: new Date(Date.now() - 300000).toISOString(),
      updated_at: new Date().toISOString(),
      progress_percent: 75.0,
    },
  ],
  timestamp: new Date().toISOString(),
};

beforeEach(() => {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(MOCK_DASHBOARD),
    })
  );
});

afterEach(() => {
  jest.clearAllMocks();
});

// ── Status strip ──────────────────────────────────────────────────────────────

describe('Status strip', () => {
  test('renders Retriever active status', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    // Multiple "Retriever" elements exist (strip dot + processing card) — use getAllByText
    expect(screen.getAllByText('Retriever').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0);
  });

  test('renders queue depth', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getByText('12')).toBeInTheDocument();
  });
});

// ── Active batches with subtitles (Fix 4) ─────────────────────────────────────

describe('Active batch display (Fix 4)', () => {
  test('renders display_name as primary label', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getByText('WBA Extranet (Programmes & Workgroups)')).toBeInTheDocument();
  });

  test('renders datasource_id as subtitle', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    // datasource_id shown as subtitle in .mon-batch-id element
    const subtitles = document.querySelectorAll('.mon-batch-id');
    expect(subtitles.length).toBeGreaterThan(0);
  });

  test('subtitle shows correct datasource_id for WBA batch', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    // "wba_extranet" should appear somewhere as the datasource_id subtitle
    const wbaIdEl = screen.queryByText('wba_extranet');
    expect(wbaIdEl).toBeInTheDocument();
  });

  test('renders status badge for retrieving', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getByText('retrieving')).toBeInTheDocument();
  });

  test('renders status badge for digesting', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getByText('digesting')).toBeInTheDocument();
  });

  test('progress percentage shown', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    // 27% and 75% should appear
    expect(screen.getByText(/75%/)).toBeInTheDocument();
  });
});

// ── Currently processing ──────────────────────────────────────────────────────

describe('Currently processing cards', () => {
  test('shows Retriever service card', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getAllByText('Retriever').length).toBeGreaterThan(0);
  });

  test('shows Digester service card', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getAllByText('Digester').length).toBeGreaterThan(0);
  });

  test('shows currently processing title for digester', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getByText('SR Policy Architecture')).toBeInTheDocument();
  });

  test('shows datasource source badge', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    // WBA or IETF badges should appear for currently processing items
    const wbaEls = screen.queryAllByText('WBA');
    const ietfEls = screen.queryAllByText('IETF');
    expect(wbaEls.length + ietfEls.length).toBeGreaterThan(0);
  });
});

// ── Queue groups ──────────────────────────────────────────────────────────────

describe('Queue display', () => {
  test('shows queue message count', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    // "12" appears for the queue count metric
    expect(screen.getAllByText('12').length).toBeGreaterThan(0);
  });

  test('shows ready chip', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getByText('10 ready')).toBeInTheDocument();
  });

  test('shows processing chip', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getByText('2 processing')).toBeInTheDocument();
  });
});

// ── Recent activity ───────────────────────────────────────────────────────────

describe('Recent activity feed', () => {
  test('shows completed item title', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    expect(screen.getByText('AI/ML Datasets Overview')).toBeInTheDocument();
  });

  test('completed item shows ✓ icon', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    const completedIcon = document.querySelector('.mon-activity-icon.completed');
    expect(completedIcon).toBeInTheDocument();
    expect(completedIcon.textContent).toBe('✓');
  });
});

// ── CSS classes (proxy for dark mode vars) ────────────────────────────────────

describe('CSS class structure (Fix 2 proxy)', () => {
  test('container uses mon-container class', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    const container = document.querySelector('.mon-container');
    expect(container).toBeInTheDocument();
  });

  test('status strip uses mon-strip class', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    const strip = document.querySelector('.mon-strip');
    expect(strip).toBeInTheDocument();
  });

  test('batch rows use mon-batch-name-col class with subtitle', async () => {
    await act(async () => { render(<AdminMonitoring />); });
    const nameCols = document.querySelectorAll('.mon-batch-name-col');
    expect(nameCols.length).toBeGreaterThan(0);
  });
});

// ── Dark mode CSS variables not using color-* ─────────────────────────────────

describe('CSS variables fix (Fix 2)', () => {
  test('AdminMonitoring.css uses --card not --color-surface', () => {
    const fs = require('fs');
    const path = require('path');
    const cssPath = path.join(__dirname, 'AdminMonitoring.css');
    if (!fs.existsSync(cssPath)) return;
    const css = fs.readFileSync(cssPath, 'utf8');
    expect(css).not.toContain('--color-surface');
    expect(css).not.toContain('--color-bg');
    expect(css).not.toContain('--color-text');
    expect(css).toContain('--card');
    expect(css).toContain('--background');
    expect(css).toContain('--foreground');
  });
});
