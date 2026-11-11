const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const { chromium } = require('playwright');

const url = 'http://127.0.0.1:8000/';
const html = readFileSync(join(__dirname, 'index.html'), 'utf8');
const winner = { provider: 'openai', answer: 'Selected answer', confidence: 80 };
const answer = '<b>literal HTML</b>';
const result = {
  winner,
  fused: [{ id: 'openai', score: 0.0492 }],
  all: [winner, { provider: 'anthropic', answer, confidence: 65 }],
};

test('question form', async (t) => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH });
  t.after(() => browser.close());

  async function submit(t, respond) {
    const page = await browser.newPage();
    t.after(() => page.close());
    page.setDefaultTimeout(2000);
    await page.route('**/*', (route) => {
      const request = route.request();
      if (request.url() === url) return route.fulfill({ contentType: 'text/html', body: html });
      if (request.url() === url + 'ask' && request.method() === 'POST') return respond(route);
      return route.abort();
    });
    await page.goto(url);
    await page.locator('#q').fill('Example question');
    await page.getByRole('button', { name: '질의' }).click();
    return page;
  }

  await t.test('renders ranked result and displays HTML in candidate as text', async (t) => {
    const page = await submit(t, (route) => route.fulfill({ json: result }));
    const cards = page.locator('#all .provider');
    await cards.nth(1).waitFor();
    assert.match(await page.locator('#winner').textContent(), /Selected answer/);
    assert.match(await page.locator('#winner').textContent(), /RRF score=0\.0492/);
    assert.equal(await cards.count(), 2);
    assert.match(await cards.nth(1).textContent(), /confidence=65/);
    assert.ok((await cards.nth(1).textContent()).includes(answer));
    assert.equal(await cards.nth(1).locator('b').count(), 0);
  });

  await t.test('ignores repeated submissions while a question is pending', async (t) => {
    let releaseResponse;
    const pendingResponse = new Promise((resolve) => { releaseResponse = resolve; });
    t.after(() => releaseResponse());
    const page = await submit(t, async (route) => {
      await pendingResponse;
      await route.fulfill({ json: result });
    });
    const button = page.getByRole('button', { name: '질의' });

    // requestSubmit also exercises the guard independently of the disabled button.
    const duplicateRequests = await page.evaluate(() => {
      const originalFetch = window.fetch;
      let count = 0;
      window.fetch = (...args) => { count++; return originalFetch(...args); };
      try {
        document.getElementById('form').requestSubmit();
        document.getElementById('form').requestSubmit();
        return count;
      } finally {
        window.fetch = originalFetch;
      }
    });
    assert.equal(duplicateRequests, 0);
    assert.equal(await button.isDisabled(), true);

    releaseResponse();
    await page.locator('#winner').filter({ hasText: 'Selected answer' }).waitFor();
    assert.equal(await button.isEnabled(), true);
    assert.equal(await page.locator('#all .provider').count(), 2);

    await page.locator('#q').fill('Next question');
    const nextRequest = page.waitForRequest((request) =>
      request.url() === url + 'ask' && request.postDataJSON().query === 'Next question');
    await button.click();
    await nextRequest;
    await page.locator('#winner').filter({ hasText: 'Selected answer' }).waitFor();
    assert.equal(await page.locator('#all .provider').count(), 2);
  });

  const errors = [
    ['connection failure', (route) => route.abort('failed'), /오류:/],
    ['non-JSON response', (route) => route.fulfill({ body: '<p>Unavailable</p>' }), /오류:/],
    ['HTTP 400 with API detail', (route) => route.fulfill({
      status: 400, json: { detail: 'query is required' },
    }), /오류: query is required/],
    ['HTTP 503 without API detail', (route) => route.fulfill({
      status: 503, json: {},
    }), /오류: HTTP 503/],
  ];

  for (const [name, respond, message] of errors) {
    await t.test(name, async (t) => {
      let attempts = 0;
      const page = await submit(t, (route) =>
        ++attempts === 1 ? respond(route) : route.fulfill({ json: result }));
      await page.locator('#winner').filter({ hasText: message }).waitFor();
      assert.equal(await page.locator('#all .provider').count(), 0);
      const button = page.getByRole('button', { name: '질의' });
      assert.equal(await button.isEnabled(), true);
      await button.click();
      await page.locator('#winner').filter({ hasText: 'Selected answer' }).waitFor();
      assert.equal(await page.locator('#all .provider').count(), 2);
    });
  }
});
