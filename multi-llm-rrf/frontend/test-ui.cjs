const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const { chromium } = require('playwright');

const url = 'http://127.0.0.1:8000/';
const html = readFileSync(join(__dirname, 'index.html'), 'utf8');
const winner = { provider: 'openai', answer: 'Selected answer' };
const answer = '<b>literal HTML</b>';
const result = {
  winner,
  fused: [{ id: 'openai', score: 2 / 61 }],
  all: [winner, { provider: 'anthropic', answer }],
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
      if (request.url() === url + 'settings/keys') return route.fulfill({ json: { providers: { openai: true, anthropic: true } } });
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
    assert.match(await page.locator('#winner').textContent(), /RRF score=0\.0328/);
    assert.equal(await cards.count(), 2);
    assert.doesNotMatch(await page.locator('#winner').textContent(), /confidence|undefined/i);
    assert.doesNotMatch(await page.locator('#all').textContent(), /confidence|undefined/i);
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

  async function settingsPage(t, { getKeys, saveKey, loadModels }) {
    const page = await browser.newPage();
    t.after(() => page.close());
    page.setDefaultTimeout(2500);
    await page.route('**/*', (route) => {
      const request = route.request();
      if (request.url() === url) return route.fulfill({ contentType: 'text/html', body: html });
      if (request.url() === url + 'settings/keys') {
        return request.method() === 'POST' ? saveKey(route) : getKeys(route);
      }
      if (request.url() === url + 'settings/models') return loadModels(route);
      if (request.url() === url + 'ask') return route.fulfill({ json: result });
      return route.abort();
    });
    await page.goto(url);
    return page;
  }

  await t.test('loads missing-key status and asks for registration before a question', async (t) => {
    let reads = 0;
    const page = await settingsPage(t, {
      getKeys: route => { reads++; return route.fulfill({ json: { providers: { openai: false, anthropic: false } } }); },
    });
    await page.locator('#key-status').filter({ hasText: '등록' }).waitFor();
    assert.equal(reads, 1);
    assert.equal(await page.getByRole('button', { name: '질의', exact: true }).isDisabled(), true);
    assert.equal(await page.locator('#api-key').getAttribute('type'), 'password');
    assert.equal(await page.locator('#api-key').isEnabled(), true);
    assert.equal(await page.getByRole('radio', { name: /Google/ }).isDisabled(), true);
  });

  await t.test('configured keys are never shown or editable', async (t) => {
    const page = await settingsPage(t, {
      getKeys: route => route.fulfill({ json: { providers: { openai: true, anthropic: true } } }),
    });
    await page.locator('#key-status').filter({ hasText: '등록' }).waitFor();
    assert.equal(await page.locator('#api-key').isVisible(), false);
    assert.equal(await page.getByRole('button', { name: '질의', exact: true }).isEnabled(), true);
    assert.equal(await page.locator('#openai-key-state').textContent(), '등록됨');
    await page.getByRole('radio', { name: /Anthropic/ }).check();
    assert.equal(await page.locator('#api-key').isVisible(), false);
  });

  await t.test('registers both missing keys once, clears secrets, survives refresh, and enables questions', async (t) => {
    const providers = { openai: false, anthropic: false };
    const saved = [];
    let firstRequestSeen;
    const started = new Promise(resolve => { firstRequestSeen = resolve; });
    let release;
    const held = new Promise(resolve => { release = resolve; });
    t.after(() => release());
    const page = await settingsPage(t, {
      getKeys: route => route.fulfill({ json: { providers } }),
      saveKey: async route => {
        const body = route.request().postDataJSON();
        saved.push(body);
        firstRequestSeen();
        if (saved.length === 1) await held;
        providers[body.provider] = true;
        return route.fulfill({ status: 201, json: { providers, provider: body.provider, verified: true, models: [{id: 'test-model', display_name: 'Test model'}] } });
      },
    });
    await page.locator('#api-key').fill('test-openai-key-123456');
    await page.getByRole('button', { name: '키 확인 후 저장', exact: true }).click();
    await started;
    await page.locator('#key-form').evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
    assert.equal(saved.length, 1);
    assert.equal(await page.locator('#api-key').inputValue(), '');
    assert.equal(await page.getByRole('button', { name: '키 확인 후 저장', exact: true }).isDisabled(), true);
    release();
    await page.locator('#openai-key-state').filter({ hasText: '등록됨' }).waitFor();
    assert.equal(await page.getByRole('radio', { name: /Anthropic/ }).isChecked(), true);
    await page.locator('#api-key').fill('test-anthropic-key-123456');
    await page.getByRole('button', { name: '키 확인 후 저장', exact: true }).click();
    await page.locator('#anthropic-key-state').filter({ hasText: '등록됨' }).waitFor();
    assert.equal(await page.locator('#model-list li').count(), 1);
    assert.match(await page.locator('#model-list').textContent(), /test-model/);
    assert.deepEqual(saved, [
      { provider: 'openai', api_key: 'test-openai-key-123456' },
      { provider: 'anthropic', api_key: 'test-anthropic-key-123456' },
    ]);
    assert.equal(await page.locator('#api-key').inputValue(), '');
    assert.equal(await page.locator('#api-key').isVisible(), false);
    assert.deepEqual(await page.evaluate(() => [localStorage.length, sessionStorage.length]), [0, 0]);
    await page.reload();
    await page.locator('#anthropic-key-state').filter({ hasText: '등록됨' }).waitFor();
    assert.equal(await page.locator('#api-key').isVisible(), false);
    await page.locator('#q').fill('Example question');
    await page.getByRole('button', { name: '질의', exact: true }).click();
    await page.locator('#winner').filter({ hasText: 'Selected answer' }).waitFor();
  });

  await t.test('failed key save clears the input and allows a fresh retry', async (t) => {
    let writes = 0;
    const page = await settingsPage(t, {
      getKeys: route => route.fulfill({ json: { providers: { openai: false, anthropic: true } } }),
      saveKey: route => ++writes === 1
        ? route.fulfill({ status: 500, json: { detail: 'API 키를 저장하지 못했습니다.' } })
        : route.fulfill({ status: 201, json: { providers: { openai: true, anthropic: true }, provider: 'openai', verified: true, models: [] } }),
    });
    await page.locator('#api-key').fill('test-key-for-error-123456');
    await page.getByRole('button', { name: '키 확인 후 저장', exact: true }).click();
    await page.locator('#key-status').filter({ hasText: '저장하지 못했습니다' }).waitFor();
    assert.equal(await page.locator('#api-key').inputValue(), '');
    assert.doesNotMatch(await page.locator('body').textContent(), /test-key-for-error/);
    await page.locator('#api-key').fill('test-retry-key-123456');
    await page.getByRole('button', { name: '키 확인 후 저장', exact: true }).click();
    await page.locator('#openai-key-state').filter({ hasText: '등록됨' }).waitFor();
    assert.equal(await page.getByRole('button', { name: '질의', exact: true }).isEnabled(), true);
  });

  await t.test('status lookup failure keeps settings disabled until retry succeeds', async (t) => {
    let reads = 0;
    const page = await settingsPage(t, {
      getKeys: route => ++reads === 1
        ? route.abort('failed')
        : route.fulfill({ json: { providers: { openai: true, anthropic: false } } }),
    });
    await page.locator('#key-status').filter({ hasText: '확인하지 못했습니다' }).waitFor();
    assert.equal(await page.locator('#api-key').isDisabled(), true);
    assert.equal(await page.getByRole('button', { name: '질의', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: '등록 상태 다시 확인' }).click();
    await page.locator('#openai-key-state').filter({ hasText: '등록됨' }).waitFor();
    assert.equal(await page.getByRole('radio', { name: /Anthropic/ }).isChecked(), true);
    assert.equal(await page.locator('#api-key').isEnabled(), true);
  });

  await t.test('already-registered conflict refreshes status instead of overwriting', async (t) => {
    let registered = false;
    const page = await settingsPage(t, {
      getKeys: route => route.fulfill({ json: { providers: { openai: registered, anthropic: true } } }),
      saveKey: route => {
        registered = true;
        return route.fulfill({ status: 409, json: { detail: '이미 등록된 API 키입니다.' } });
      },
    });
    await page.locator('#api-key').fill('test-conflict-key-123456');
    await page.getByRole('button', { name: '키 확인 후 저장', exact: true }).click();
    await page.locator('#openai-key-state').filter({ hasText: '등록됨' }).waitFor();
    assert.equal(await page.locator('#api-key').isVisible(), false);
    assert.equal(await page.getByRole('button', { name: '질의', exact: true }).isEnabled(), true);
  });


  await t.test('existing key model lookup is explicit and displays returned names as text', async (t) => {
    const lookups = [];
    const page = await settingsPage(t, {
      getKeys: route => route.fulfill({json:{providers:{openai:true,anthropic:true}}}),
      loadModels: route => {
        lookups.push(route.request().postDataJSON());
        return route.fulfill({json:{provider:'openai',verified:true,models:[
          {id:'embedding-test',display_name:'embedding-test'},
          {id:'model-x',display_name:'<img src=x onerror=alert(1)>'},
        ]}});
      },
    });
    await page.locator('#openai-key-state').filter({hasText:'등록됨'}).waitFor();
    assert.equal(lookups.length,0);
    await page.getByRole('button',{name:'연결 확인·모델 조회',exact:true}).click();
    await page.locator('#model-list li').nth(1).waitFor();
    assert.deepEqual(lookups,[{provider:'openai'}]);
    assert.match(await page.locator('#model-list').textContent(),/embedding-test/);
    assert.ok((await page.locator('#model-list').textContent()).includes('<img src=x onerror=alert(1)>'));
    assert.equal(await page.locator('#model-list img').count(),0);
    assert.equal(await page.locator('#api-key').isVisible(),false);
    await page.getByRole('radio',{name:/Anthropic/}).check();
    assert.equal(await page.locator('#model-catalog').isVisible(),false);
    await page.getByRole('radio',{name:/OpenAI/}).check();
    assert.equal(await page.locator('#model-list li').count(),2);
    await page.getByRole('button',{name:'등록 상태 다시 확인'}).click();
    await page.locator('#model-catalog').waitFor({state:'hidden'});
  });

  await t.test('model request is guarded while pending and empty successful list is still verified', async (t) => {
    let requests=0,release,seen;
    const pending=new Promise(resolve=>{release=resolve;});
    const started=new Promise(resolve=>{seen=resolve;});
    t.after(()=>release());
    const page=await settingsPage(t,{
      getKeys:route=>route.fulfill({json:{providers:{openai:true,anthropic:true}}}),
      loadModels:async route=>{requests++;seen();await pending;return route.fulfill({json:{provider:'openai',verified:true,models:[]}});},
    });
    const button=page.getByRole('button',{name:'연결 확인·모델 조회',exact:true});
    await button.click();await started;
    await button.evaluate(element=>element.dispatchEvent(new Event('click')));
    assert.equal(requests,1);
    assert.equal(await button.isDisabled(),true);
    release();
    await page.locator('#model-status').filter({hasText:'조회된 모델이 없습니다'}).waitFor();
    assert.equal(await button.isEnabled(),true);
    assert.equal(await page.locator('#api-key').isVisible(),false);
  });

  await t.test('permission failure is shown without classifying a stored key as invalid and can retry', async (t) => {
    let attempts=0;
    const page=await settingsPage(t,{
      getKeys:route=>route.fulfill({json:{providers:{openai:true,anthropic:true}}}),
      loadModels:route=> ++attempts===1
        ? route.fulfill({status:403,json:{detail:'모델 목록 조회 권한이 없어 확인할 수 없습니다.'}})
        : route.fulfill({json:{provider:'openai',verified:true,models:[{id:'model-a',display_name:'Model A'}]}}),
    });
    const button=page.getByRole('button',{name:'연결 확인·모델 조회',exact:true});
    await button.click();
    await page.locator('#model-status').filter({hasText:'조회 권한'}).waitFor();
    assert.doesNotMatch(await page.locator('#model-status').textContent(),/잘못된 키|유효하지/);
    assert.equal(await page.locator('#openai-key-state').textContent(),'등록됨');
    assert.equal(await page.locator('#api-key').isVisible(),false);
    await button.click();
    await page.locator('#model-list li').waitFor();
    assert.equal(attempts,2);
  });

  await t.test('failed validation never marks an unsaved key as registered', async (t) => {
    let writes=0;
    const page=await settingsPage(t,{
      getKeys:route=>route.fulfill({json:{providers:{openai:false,anthropic:true}}}),
      saveKey:route=>{writes++;return route.fulfill({status:401,json:{detail:'API 키 인증에 실패했습니다.'}});},
    });
    await page.locator('#api-key').fill('synthetic-invalid-key');
    await page.getByRole('button',{name:'키 확인 후 저장',exact:true}).click();
    await page.locator('#key-status').filter({hasText:'인증에 실패'}).waitFor();
    assert.equal(writes,1);
    assert.equal(await page.locator('#openai-key-state').textContent(),'미등록');
    assert.equal(await page.locator('#api-key').inputValue(),'');
    assert.equal(await page.getByRole('button',{name:'질의',exact:true}).isDisabled(),true);
    assert.doesNotMatch(await page.locator('body').textContent(),/synthetic-invalid-key/);
  });

  await t.test('malformed model result is rejected and stale catalog is cleared on lookup failure', async (t) => {
    let attempt=0;
    const page=await settingsPage(t,{
      getKeys:route=>route.fulfill({json:{providers:{openai:true,anthropic:true}}}),
      loadModels:route=>route.fulfill({json:++attempt===1
        ? {provider:'openai',verified:true,models:[{id:'model-a',display_name:'Model A'}]}
        : {provider:'anthropic',verified:true,models:[{id:'wrong-provider',display_name:'Wrong'}]}}),
    });
    const button=page.getByRole('button',{name:'연결 확인·모델 조회',exact:true});
    await button.click();await page.locator('#model-list li').waitFor();
    await button.click();
    await page.locator('#model-status').filter({hasText:'확인하지 못했습니다'}).waitFor();
    assert.equal(await page.locator('#model-catalog').isVisible(),false);
    assert.equal(await button.isEnabled(),true);
    assert.deepEqual(await page.evaluate(()=>[localStorage.length,sessionStorage.length]),[0,0]);
  });

});
