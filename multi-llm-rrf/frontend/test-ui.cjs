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
      const page = await submit(t, respond);
      await page.locator('#winner').filter({ hasText: message }).waitFor();
      assert.equal(await page.locator('#all .provider').count(), 0);
    });
  }
});
