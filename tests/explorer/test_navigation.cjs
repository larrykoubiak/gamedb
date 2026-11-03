// Run with Playwright available to Node: node tests/explorer/test_navigation.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const requests = [];
  const systems = [
    {id: 1, manufacturer: 'Example', name: 'Tiny Platform', category: 'computer', gameCount: 1},
    {id: 42, manufacturer: 'Nintendo', name: 'NES', category: 'console', gameCount: 201},
  ];
  const game = {
    softwareId: 123, systemId: 42, manufacturer: 'Nintendo', systemName: 'NES',
    title: 'Mario', identityBasis: 'title_fallback', score: 0, packageCount: 1,
    regions: [], languages: [], revisions: [], releaseDates: [],
    dumpStatuses: [], dumpModifications: [], breakdown: [], media: {
      boxart: {path: 'test/box art.png', matchBasis: 'preferred_release_exact', regionMatch: 'exact'},
      snap: {path: 'test/gameplay.png', matchBasis: 'preferred_release_exact', regionMatch: 'exact'},
      logo: {path: 'test/broken.png', matchBasis: 'preferred_release_exact', regionMatch: 'exact'},
    },
  };
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname.startsWith('/api/')) {
      requests.push(req.url);
      let payload;
      if (url.pathname === '/api/systems') payload = systems;
      else if (url.pathname === '/api/capabilities') payload = {softwareCorrections: true};
      else if (url.pathname === '/api/metadata-options') {
        const values = url.searchParams.get('key') === 'genre' ? ['Action', 'Adventure']
          : ['Nintendo', "Bob's Studio"];
        const search = (url.searchParams.get('search') || '').toLowerCase();
        const items = values.filter(value => value.toLowerCase().includes(search))
          .map(value => ({value, count: 201}));
        payload = {items, total: items.length};
      }
      else if (url.pathname.endsWith('/correction-targets')) payload = [];
      else if (/\/api\/software\/\d+\/(releases|facts)$/.test(url.pathname)) payload = [];
      else payload = {items: [game], total: 201, page: Number(url.searchParams.get('page') || 1), pageSize: 100};
      res.setHeader('Content-Type', 'application/json');
      return res.end(JSON.stringify(payload));
    }
    if (url.pathname === '/system-icons.json') {
      res.setHeader('Content-Type', 'application/json');
      const icons = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../gamedb/explorer/assets/system-icons.json'), 'utf8'));
      return res.end(JSON.stringify({...icons, 'Nintendo\x1fNES': icons['Nintendo\x1fNintendo Entertainment System']}));
    }
    if (url.pathname.startsWith('/media/test/')) {
      if (url.pathname.endsWith('broken.png')) { res.statusCode = 404; return res.end(); }
      res.setHeader('Content-Type', 'image/png');
      return res.end(fs.readFileSync(path.resolve(__dirname,
        '../../gamedb/explorer/assets/system-icons/pixel-nintendo-nintendo-entertainment-system-a9c58d62.png')));
    }
    const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
    const file = path.resolve(__dirname, '../../gamedb/explorer/assets', name);
    res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.png') ? 'image/png' : 'text/html');
    res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.locator('.game-row').waitFor();
    assert.equal(await page.locator('#system-name').innerText(), 'All platforms');
    assert(requests.some(url => url.startsWith('/api/titles?')));
    assert(!requests.some(url => url.startsWith('/api/systems/1/titles')));
    assert.equal(await page.locator('.platform-cell').innerText(), 'NES\nNintendo');
    await page.waitForFunction(() => document.querySelector('.platform-cell img')?.naturalWidth > 0);
    assert.equal(await page.locator('.system-button .platform-icon-fallback').count(), 1);
    const thumbnail = page.getByRole('button', {name: 'Enlarge Mario — Artwork', exact: true});
    await thumbnail.click();
    const artwork = page.locator('#artwork-dialog');
    await artwork.waitFor();
    await page.waitForFunction(() => document.querySelector('#artwork-image').naturalWidth > 0);
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Mario — Box art');
    assert.equal(await page.locator('#artwork-position').innerText(), 'Image 1 of 3');
    assert((await page.locator('#artwork-image').getAttribute('src')).endsWith('/media/test/box%20art.png'));
    assert.equal(page.context().pages().length, 1);
    await page.getByRole('button', {name: 'Next image', exact: true}).click();
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Mario — Gameplay');
    assert.equal(await page.locator('#artwork-position').innerText(), 'Image 2 of 3');
    await page.keyboard.press('ArrowLeft');
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Mario — Box art');
    await page.keyboard.press('ArrowLeft');
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Mario — Logo');
    await page.locator('#artwork-error').waitFor();
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(() => document.querySelector('#artwork-image').naturalWidth > 0);
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Mario — Box art');
    assert.equal(await page.locator('#artwork-error').isVisible(), false);
    await page.keyboard.press('Escape');
    await artwork.waitFor({state: 'hidden'});
    assert(await thumbnail.evaluate(element => element === document.activeElement));
    await page.locator('.expand-button').click();
    const gameplay = page.getByRole('button', {name: 'Enlarge Mario — Gameplay', exact: true});
    await gameplay.click();
    await artwork.waitFor();
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Mario — Gameplay');
    assert.equal(await page.locator('#artwork-position').innerText(), 'Image 2 of 3');
    await page.getByRole('button', {name: 'Previous image', exact: true}).click();
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Mario — Box art');
    await page.locator('#artwork-close').click();
    await artwork.waitFor({state: 'hidden'});
    await gameplay.click();
    await artwork.waitFor();
    await page.mouse.click(2, 2);
    await artwork.waitFor({state: 'hidden'});
    await page.getByRole('button', {name: 'Enlarge Mario — Logo', exact: true}).click();
    await page.locator('#artwork-error').waitFor();
    await page.keyboard.press('Escape');
    await artwork.waitFor({state: 'hidden'});
    await page.setViewportSize({width: 390, height: 844});
    await thumbnail.click();
    await artwork.waitFor();
    const bounds = await artwork.boundingBox();
    assert(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= 390 && bounds.y + bounds.height <= 844);
    await page.getByRole('button', {name: 'Next image', exact: true}).click();
    assert.equal(await page.locator('#artwork-position').innerText(), 'Image 2 of 3');
    await page.keyboard.press('Escape');
    await artwork.waitFor({state: 'hidden'});
    await page.setViewportSize({width: 1280, height: 720});
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'single-artwork-fixture';
      document.body.append(container);
      renderArtworkGallery(container, {boxart: {path:'test/box art.png', matchBasis:'preferred_release_exact', regionMatch:'exact'}}, 'Single image');
    });
    await page.getByRole('button', {name:'Enlarge Single image — Box art', exact:true}).click();
    assert.equal(await page.locator('#artwork-navigation').isVisible(), false);
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Single image — Box art');
    await page.keyboard.press('Escape');
    await artwork.waitFor({state: 'hidden'});
    await page.evaluate(() => document.querySelector('#single-artwork-fixture').remove());
    await page.locator('#system-category').selectOption('console');
    assert.equal(await page.locator('#system-tree .system-button').count(), 1);
    assert.equal(await page.locator('#system-tree summary').innerText(), 'Nintendo');
    assert.equal(await page.locator('#system-count').innerText(), '1 / 2 systems');
    await page.locator('#system-filter').fill('Tiny');
    assert.equal(await page.locator('#system-tree').innerText(), 'No matching systems.');
    await page.locator('#system-category').selectOption('computer');
    assert.equal(await page.locator('#system-tree .system-button').count(), 1);
    await page.locator('#system-filter').fill('');
    await page.locator('#system-category').selectOption('arcade');
    assert.equal(await page.locator('#system-tree').innerText(), 'No matching systems.');
    await page.locator('#system-category').selectOption('');
    assert.equal(await page.locator('#system-tree .system-button').count(), 2);
    const failedLogos = await page.evaluate(async () => {
      const failures = await Promise.all([...new Set(Object.values(state.systemIcons))].map(async name => {
        const image = new Image();
        image.src = `/system-icons/${name}`;
        try { await image.decode(); return null; } catch { return name; }
      }));
      return failures.filter(Boolean);
    });
    assert.deepEqual(failedLogos, []);
    assert.equal(await page.locator('.metadata-filter').count(), 10);
    assert.equal(await page.locator('.metadata-filter[data-key="description"]').count(), 0);
    const genre = page.locator('.metadata-filter[data-key="genre"]');
    await genre.locator('summary').click();
    await genre.locator('label').filter({hasText: 'Action'}).getByRole('checkbox').check();
    await page.waitForFunction(() => state.metadataFilters.genre?.includes('Action'));
    await genre.locator('label').filter({hasText: 'Adventure'}).getByRole('checkbox').check();
    await page.waitForFunction(() => state.metadataFilters.genre?.length === 2);
    assert.equal(await page.locator('#active-metadata-filters button').count(), 2);
    await page.keyboard.press('Escape');
    await page.getByRole('button', {name: 'Remove Genre filter: Adventure', exact: true}).click();
    const developer = page.locator('.metadata-filter[data-key="developer"]');
    await developer.locator('summary').click();
    await developer.locator('input[type="search"]').fill('Nintendo');
    await developer.locator('label').filter({hasText: 'Nintendo'}).getByRole('checkbox').check();
    await page.waitForFunction(() => state.metadataFilters.developer?.includes('Nintendo'));
    await page.keyboard.press('Escape');
    assert.equal(await developer.getAttribute('open'), null);
    await page.locator('#game-filter').fill('Mario');
    await page.waitForResponse(response => response.url().includes('/api/titles?') && response.url().includes('q=Mario'));
    await page.locator('#next-page').click();
    await page.waitForFunction(() => document.querySelector('#page-label').textContent.includes('Page 2'));
    assert(requests.some(url => url.includes('/api/titles?page=2') && url.includes('q=Mario')));
    assert(requests.some(url => {
      const parsed = new URL(url, 'http://localhost');
      const filters = JSON.parse(parsed.searchParams.get('filters') || '{}');
      return parsed.searchParams.get('page') === '2' && filters.genre?.includes('Action')
        && filters.developer?.includes('Nintendo');
    }));
    await page.locator('summary').filter({hasText: 'Nintendo'}).click();
    await page.locator('.system-button').filter({hasText: 'NES'}).click();
    await page.waitForFunction(() => document.querySelector('#system-name').textContent === 'NES');
    await page.locator('.game-row').waitFor();
    assert.equal(await page.locator('#game-filter').inputValue(), 'Mario');
    assert.equal(await page.locator('#active-metadata-filters button').count(), 2);
    assert(requests.some(url => url.includes('/api/systems/42/titles?page=1') && url.includes('q=Mario')));
    await page.locator('#system-category').selectOption('computer');
    assert.equal(await page.locator('#system-name').innerText(), 'NES');
    assert.equal(await page.locator('#game-filter').inputValue(), 'Mario');
    await page.locator('#all-platforms').click();
    await page.locator('.game-row').waitFor();
    assert.equal(await page.locator('#system-name').innerText(), 'All platforms');
    await page.locator('#clear-metadata-filters').click();
    assert.equal(await page.locator('#active-metadata-filters button').count(), 0);
    await page.waitForFunction(() => !Object.keys(state.metadataFilters).length);
    await page.evaluate(() => openCorrectionDialog({sourceTitle: 'Mario', releaseContentSignature: 'test'}, 123, 42));
    await page.locator('#correction-target-filter').fill('Luigi');
    await page.waitForResponse(response => response.url().includes('/api/systems/42/correction-targets'));
    assert.deepEqual(errors, []);
    console.log('Browser navigation passed: categories, combined tree filters, global default, search, paging, platform scope, preserved query, correction platform.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
