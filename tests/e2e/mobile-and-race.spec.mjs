import { expect, test } from '@playwright/test';

const key = 'a'.repeat(64);
const hash = 'b'.repeat(64);
const publication = {
  version: '20.2',
  dataDate: '2026-07-16',
  runId: 2002,
  publicationKey: key,
  contentHash: hash,
  publicationPhase: 'complete',
  dataState: 'partial',
  completeness: 92,
  dataCompleteness: 92,
  degradedSources: ['international_context'],
};

function rankingRow(horizon, symbol) {
  return {
    symbol,
    name: `TEST-${horizon}`,
    model: 'short',
    horizon,
    rank: 1,
    market: 'listed',
    industry: 'test',
    strategy: 'momentum_breakout',
    opportunityScore: 70 + horizon,
    rawOpportunityScore: 70 + horizon,
    netOpportunityScore: 67 + horizon,
    riskScore: 28,
    completeness: 96,
    confidence: 80,
    dataDate: publication.dataDate,
    publicVisible: true,
    reasons: ['deterministic fixture'],
    risks: ['fixture risk'],
  };
}

function homePayload() {
  const dailyReport = {
    ...publication,
    source: 'v20-atomic-base-report',
    report: {
      oneLine: 'Deterministic daily market summary.',
      marketStrength: { level: 'neutral', explanation: 'fixture' },
      institutionalDirection: { direction: 'neutral', explanation: 'fixture' },
      hotIndustries: [],
      focusStocks: [],
      majorRisks: [],
      watchlistChanges: [],
    },
  };
  return {
    ...publication,
    sourceDates: { listed: publication.dataDate, otc: publication.dataDate },
    market: {
      regime: 'neutral',
      regimeScore: -28,
      confidence: 77,
      taiex: { value: 24500, changePercent: 0.25, source: 'TWSE OpenAPI', dataDate: publication.dataDate },
      tpex: { value: 281, changePercent: -0.14, source: 'TPEx OpenAPI', dataDate: publication.dataDate },
      txFutures: { value: 24460, changePoints: -35, source: 'TAIFEX OpenAPI', session: 'regular', dataDate: publication.dataDate },
      globalContext: {},
    },
    shortTop: [],
    mediumTop: [],
    dailyReport,
    importantNews: [],
    importantNewsState: { status: 'not_recorded_in_publication', reason: 'fixture' },
  };
}

async function installApiFixtures(page) {
  await page.route('**/api/v20/home', route => route.fulfill({ json: homePayload() }));
  await page.route('**/api/v20/stocks**', route => route.fulfill({ status: 404, json: { error: { message: 'fixture' } } }));
  await page.route('**/data/latest.json**', route => route.fulfill({ json: { stocks: [], date: publication.dataDate } }));
}

test.describe('mobile truth and safe-area layout', () => {
  test.beforeEach(async ({ page }) => {
    await installApiFixtures(page);
    await page.goto('/');
    await expect(page.locator('.v20-market-card')).toHaveCount(3);
  });

  test('keeps status, sources, confidence and content readable', async ({ page }) => {
    await expect(page.locator('#dataMode')).toBeVisible();
    await expect(page.locator('.v20-regime-line span').last()).toBeVisible();

    const metrics = await page.locator('.v20-market-grid').evaluate(element => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      cardWidth: element.firstElementChild?.getBoundingClientRect().width || 0,
    }));
    expect(metrics.cardWidth).toBeGreaterThanOrEqual(230);
    expect(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth);

    const sourceFont = await page.locator('.v20-market-card em').first().evaluate(element => Number.parseFloat(getComputedStyle(element).fontSize));
    expect(sourceFont).toBeGreaterThanOrEqual(11);

    await page.evaluate(() => {
      document.documentElement.style.scrollBehavior = 'auto';
      document.body.style.scrollBehavior = 'auto';
      scrollTo(0, document.documentElement.scrollHeight);
    });
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(500);
    const overlap = await page.evaluate(() => {
      const last = document.querySelector('#app > * > :last-child');
      const nav = document.querySelector('.bottom-nav');
      if (!last || !nav) return Number.POSITIVE_INFINITY;
      return last.getBoundingClientRect().bottom - nav.getBoundingClientRect().top;
    });
    expect(overlap).toBeLessThanOrEqual(-4);
  });
});

test.describe('latest request wins', () => {
  test.beforeEach(async ({ page }) => {
    await installApiFixtures(page);
  });

  test('rapid ranking horizon changes cannot restore an old response', async ({ page }) => {
    await page.route('**/api/v20/rankings**', async route => {
      const horizon = Number(new URL(route.request().url()).searchParams.get('horizon'));
      await new Promise(resolve => setTimeout(resolve, horizon === 5 ? 350 : 20));
      await route.fulfill({ json: { ...publication, model: 'short', horizon, items: [rankingRow(horizon, `110${horizon}`)], nextCursor: null } });
    });

    await page.goto('/');
    await page.locator('[data-tab="short"]').click();
    await page.locator('#v20Horizon').selectOption('2');

    await expect(page.locator('.v20-model-card[data-v20-detail="1102"]')).toBeVisible();
    await page.waitForTimeout(450);
    await expect(page.locator('.v20-model-card[data-v20-detail="1102"]')).toBeVisible();
    await expect(page.locator('.v20-model-card[data-v20-detail="1105"]')).toHaveCount(0);
  });

  test('rapid validation horizon changes cannot relabel an old snapshot', async ({ page }) => {
    await page.route('**/api/v20/backtest**', async route => {
      const horizon = Number(new URL(route.request().url()).searchParams.get('horizon'));
      await new Promise(resolve => setTimeout(resolve, horizon === 5 ? 350 : 20));
      await route.fulfill({ json: {
        ...publication,
        model: 'short',
        horizon,
        modelVersion: `fast-${horizon}`,
        forwardSnapshot: { id: horizon, modelVersion: `fast-${horizon}`, dataDate: publication.dataDate, noLookAhead: true },
        outcomes: [],
      } });
    });

    await page.goto('/');
    await page.locator('[data-tab="validation"]').click();
    await page.locator('#v20ValidationHorizon').selectOption('2');

    await expect(page.locator('.v20-forward-snapshot strong')).toHaveText('fast-2');
    await page.waitForTimeout(450);
    await expect(page.locator('.v20-forward-snapshot strong')).toHaveText('fast-2');
  });
});
