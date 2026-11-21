// Run with Playwright available to Node: node tests/explorer/test_navigation.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const requests = [];
  const images = [];
  const systems = [
    {id: 1, manufacturer: 'Example', name: 'Tiny Platform', category: 'computer', gameCount: 1},
    {id: 42, manufacturer: 'Nintendo', name: 'NES', category: 'console', gameCount: 201},
  ];
  const softwareKey = 'a'.repeat(32);
  const softwarePath = `/software/123-${softwareKey}`;
  const sourceKey = 'b'.repeat(64);
  const sourcePath = `/software/exo/${sourceKey}`;
  const source = {
    key: sourceKey, entries: [{
      key: 'entry', title: 'DOS Adventure', sourceList: 'MS-DOS',
      facts: {description: ['An adventure for DOS.']},
      fields: {Title: 'DOS Adventure'}, alternateNames: [],
    }],
    editions: [{key: 'edition', entryKey: 'entry', title: 'DOS Adventure', label: 'Original',
      environment: 'MS-DOS', system: 'PC Compatibles', manufacturer: 'IBM'}],
    assets: [{kind: 'manual', label: 'Adventure Manual.pdf', url: '/related-media/manual',
      sources: [{sourceList: 'MS-DOS'}]}],
  };
  const game = {
    softwareId: 123, softwareKey, systemId: 42, manufacturer: 'Nintendo', systemName: 'NES',
    title: 'Mario', identityBasis: 'title_fallback', score: 0, packageCount: 1,
    regions: [], languages: [], revisions: [], releaseDates: [],
    dumpStatuses: [], dumpModifications: [], breakdown: [], media: {
      boxart: {path: 'test/box art.png', matchBasis: 'preferred_release_exact', regionMatch: 'exact'},
      snap: {path: 'test/gameplay.png', provider: 'exo'},
      logo: {path: 'test/broken.png', matchBasis: 'preferred_release_exact', regionMatch: 'exact'},
    },
  };
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname.startsWith('/api/')) {
      requests.push(req.url);
      let payload;
      if (url.pathname === '/api/systems') payload = systems;
      else if (url.pathname === '/api/capabilities') payload = {softwareCorrections: true, vgm: true};
      else if (url.pathname === '/api' + softwarePath) payload = {game, hideRomHacks: true};
      else if (url.pathname === '/api' + sourcePath) payload = {
        game: {title: 'DOS Adventure', systemName: 'PC Compatibles', manufacturer: 'IBM',
          sourceOnly: true, sourceDetailKey: sourceKey, sourceEntryKey: 'entry'}, source,
      };
      else if (url.pathname === '/api/software/123/facts') payload = [{
        key: 'description', preferredValues: ['Mario explores the Mushroom Kingdom.'],
        values: [{value: 'Mario explores the Mushroom Kingdom.', sourceProvider: 'launchbox',
          sourceDatabases: ['Nintendo NES']}],
      }];
      else if (url.pathname === '/api/metadata-options') {
        const values = url.searchParams.get('key') === 'genre' ? ['Action', 'Adventure']
          : ['Nintendo', "Bob's Studio"];
        const search = (url.searchParams.get('search') || '').toLowerCase();
        const items = values.filter(value => value.toLowerCase().includes(search))
          .map(value => ({value, count: 201}));
        payload = {items, total: items.length};
      }
      else if (url.pathname.endsWith('/soundtracks')) payload = [{
        title: 'Mario', collection: 'Test soundtrack collection', assets: [
          {kind: 'track', name: '01.spc', title: 'Opening Theme', playable: false, url: '/related-media/vgm/spc'},
          {kind: 'track', name: '02.mp3', playable: true, url: '/related-media/vgm/mp3'},
        ],
      }];
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
    if (/^\/(?:media|previews\/(?:128|320))\/test\//.test(url.pathname)) {
      images.push(url.pathname);
      if (url.pathname.endsWith('broken.png')) { res.statusCode = 404; return res.end(); }
      res.setHeader('Content-Type', 'image/png');
      return res.end(fs.readFileSync(path.resolve(__dirname,
        '../../gamedb/explorer/assets/system-icons/pixel-nintendo-nintendo-entertainment-system-a9c58d62.png')));
    }
    if (url.pathname === '/favicon.ico') { res.statusCode = 404; return res.end(); }
    if (url.pathname === '/' && url.searchParams.get('exo') === sourceKey) {
      res.writeHead(302, {Location: sourcePath});
      return res.end();
    }
    const name = ['/', softwarePath, sourcePath].includes(url.pathname) ? 'index.html' : url.pathname.slice(1);
    const file = path.resolve(__dirname, '../../gamedb/explorer/assets', name);
    res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.png') ? 'image/png' : 'text/html');
    res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => document.querySelector('.game-card .game-art')?.naturalWidth > 0);
    const catalogHome = page.getByRole('link', {name: 'GameDB Almanac home'});
    const backToCatalog = page.locator('#back-to-catalog');
    assert.equal(await catalogHome.getAttribute('aria-current'), 'page');
    assert.equal(await backToCatalog.isVisible(), false);
    assert.equal(await page.getByRole('button', {name: 'Tiles', exact: true}).getAttribute('aria-pressed'), 'true');
    assert(images.includes('/previews/320/test/box%20art.png'));
    assert(!images.some(url => url.startsWith('/media/')));
    const cardDetails = page.getByRole('link', {name: 'Open Mario on NES'});
    assert.equal(await cardDetails.getAttribute('href'), softwarePath);
    await page.locator('#game-filter').fill('Mario');
    await page.waitForResponse(res => res.url().includes('q=Mario'));
    await cardDetails.click();
    await page.waitForURL('**' + softwarePath);
    await page.getByRole('heading', {name: 'Mario', exact: true}).waitFor();
    await page.getByText('Mario explores the Mushroom Kingdom.', {exact: true}).filter({visible: true}).waitFor();
    assert.equal(await page.locator('#catalog-view').isVisible(), false);
    assert.equal(await catalogHome.getAttribute('aria-current'), null);
    assert.equal(await backToCatalog.isVisible(), true);
    assert.equal(await page.getByRole('tablist').getAttribute('aria-orientation'), 'vertical');
    assert.equal(await page.getByRole('tab', {name: 'Overview'}).getAttribute('aria-selected'), 'true');
    await page.getByRole('tab', {name: 'Overview'}).focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await page.waitForURL('**#artwork');
    await page.getByText('Gameplay · eXo', {exact: true}).waitFor();
    await page.getByRole('button', {name: 'Enlarge Mario — Gameplay'}).click();
    await page.waitForFunction(() => document.querySelector('#artwork-image').naturalWidth > 0);
    assert(images.includes('/media/test/gameplay.png'));
    await page.keyboard.press('Escape');
    await page.getByRole('tab', {name: 'Soundtracks'}).click();
    await page.waitForURL('**#soundtracks');
    await page.getByText('Mario · Test soundtrack collection', {exact: true}).click();
    const soundtrack = page.getByRole('link', {name: 'Opening Theme'});
    await soundtrack.waitFor();
    assert.equal(await soundtrack.getAttribute('href'), '/related-media/vgm/spc');
    assert.equal(await soundtrack.getAttribute('download'), '');
    await page.getByRole('button', {name: 'Play 02.mp3'}).waitFor();
    assert.equal(await page.getByRole('button', {name: 'Play Opening Theme'}).count(), 0);
    await page.setViewportSize({width: 390, height: 844});
    await page.waitForFunction(() => document.querySelector('.book-tabs').getAttribute('aria-orientation') === 'horizontal');
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.getByRole('link', {name: 'Back to catalog'}).click();
    await page.waitForURL(url => url.pathname === '/');
    assert.equal(await page.locator('#game-filter').inputValue(), 'Mario');
    assert(await cardDetails.evaluate(element => element === document.activeElement));
    await page.locator('#game-filter').fill('');
    await page.waitForResponse(res => res.url().includes('/api/titles?') && !res.url().includes('q=Mario'));
    await page.setViewportSize({width: 1280, height: 720});
    const direct = await context.newPage();
    const catalogRequests = () => requests.filter(url => /\/api\/(titles|systems)\?/.test(url)).length;
    const beforeDirect = catalogRequests();
    const origin = `http://127.0.0.1:${server.address().port}`;
    await direct.goto(origin + softwarePath + '#soundtracks');
    await direct.getByRole('tab', {name: 'Soundtracks', selected: true}).waitFor();
    await direct.reload();
    await direct.getByText('Mario · Test soundtrack collection', {exact: true}).waitFor();
    assert.equal(catalogRequests(), beforeDirect);
    await direct.goto(origin + '/?exo=' + sourceKey);
    await direct.waitForURL('**' + sourcePath);
    await direct.getByRole('heading', {name: 'DOS Adventure', exact: true}).waitFor();
    await direct.getByRole('tab', {name: 'Related media'}).click();
    const manual = direct.getByRole('link', {name: 'Adventure Manual.pdf'});
    await manual.waitFor();
    assert.equal(await manual.getAttribute('href'), '/related-media/manual');
    await direct.getByRole('tab', {name: 'Releases'}).click();
    await direct.getByRole('heading', {name: 'eXo editions'}).waitFor();
    await direct.close();
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.locator('#system-browser').isVisible(), false);
    assert((await page.locator('.game-card').boundingBox()).y < 844);
    await page.getByRole('button', {name: 'Browse platforms'}).click();
    assert.equal(await page.locator('#system-browser').isVisible(), true);
    await page.getByRole('button', {name: 'Hide platforms'}).click();
    const tags = page.locator('.metadata-filter[data-key="tags"]');
    await tags.locator('summary').click();
    const filterPanel = await tags.locator('.metadata-filter-panel').boundingBox();
    assert(filterPanel.x >= 0 && filterPanel.x + filterPanel.width <= 390);
    await page.keyboard.press('Escape');
    await page.setViewportSize({width: 1280, height: 720});
    assert.equal(await page.locator('#system-browser').isVisible(), true);
    const titleRequests = () => requests.filter(url => url.includes('/titles?')).length;
    const beforeSwitch = titleRequests();
    await page.getByRole('button', {name: 'Table', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('.game-row .game-art')?.naturalWidth > 0);
    assert(images.includes('/previews/128/test/box%20art.png'));
    assert.equal(titleRequests(), beforeSwitch);
    await page.reload();
    await page.locator('.game-row').waitFor();
    assert.equal(await page.getByRole('button', {name: 'Table', exact: true}).getAttribute('aria-pressed'), 'true');
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
    const table = page.getByRole('region', {name: 'Preferred releases'});
    assert(await table.evaluate(element => element.scrollWidth > element.clientWidth));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
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
    assert.equal(await page.locator('#system-count').innerText(), '1 / 2');
    await page.locator('#system-filter').fill('Tiny');
    assert.equal(await page.locator('#system-tree').innerText(), 'No matching platforms.');
    await page.locator('#system-category').selectOption('computer');
    assert.equal(await page.locator('#system-tree .system-button').count(), 1);
    await page.locator('#system-filter').fill('');
    await page.locator('#system-category').selectOption('arcade');
    assert.equal(await page.locator('#system-tree').innerText(), 'No matching platforms.');
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
    const hideHacks = page.getByRole('checkbox', {name: 'Hide ROM hacks'});
    assert.equal(await hideHacks.isChecked(), true);
    assert(requests.some(url => url.startsWith('/api/titles?') && url.includes('hide_rom_hacks=1')));
    const fullPage = page.waitForResponse(r => r.url().includes('/api/titles?') && !r.url().includes('hide_rom_hacks'));
    await hideHacks.uncheck();
    await fullPage;
    await page.reload();
    await page.locator('.game-row').waitFor();
    assert.equal(await hideHacks.isChecked(), false);
    const filteredSystems = page.waitForResponse(r => r.url().includes('/api/systems?hide_rom_hacks=1'));
    await hideHacks.check();
    await filteredSystems;
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
    const tableTitle = page.getByRole('link', {name: 'Open Mario on NES'});
    await tableTitle.click();
    await page.getByRole('heading', {name: 'Mario', exact: true}).waitFor();
    await catalogHome.click();
    await page.waitForURL(url => url.pathname === '/');
    assert.match(await page.locator('#page-label').innerText(), /Page 2/);
    assert.equal(await page.locator('#active-metadata-filters button').count(), 2);
    assert(await tableTitle.evaluate(element => element === document.activeElement));
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
    await page.getByRole('button', {name: 'Tiles', exact: true}).click();
    await page.locator('.game-card').waitFor();
    await page.evaluate(() => {
      const payload = state.results;
      const game = payload.items[0];
      const items = Array.from({length: 80}, (_, i) => ({
        ...game, media: {boxart: {...game.media.boxart, path: `test/lazy-${i}.png`}},
      }));
      items[79].media = {boxart: {...game.media.boxart, path: 'test/distant-broken.png'}, snap: game.media.snap};
      renderGames({...payload, items});
    });
    await page.waitForFunction(() => document.querySelector('.game-card .game-art')?.naturalWidth > 0);
    assert(!images.includes('/previews/320/test/distant-broken.png'));
    const distant = page.locator('.game-card').last();
    await distant.scrollIntoViewIfNeeded();
    await page.waitForFunction(() => {
      const img = document.querySelector('.game-card:last-child .game-art');
      return img?.naturalWidth > 0 && img.currentSrc.endsWith('/previews/320/test/gameplay.png');
    });
    await distant.locator('.artwork-zoom').click();
    assert.equal(await page.locator('#artwork-caption').innerText(), 'Mario — Gameplay');
    await page.keyboard.press('Escape');
    await page.evaluate(() => openCorrectionDialog({sourceTitle: 'Mario', releaseContentSignature: 'test'}, 123, 42));
    await page.locator('#correction-target-filter').fill('Luigi');
    await page.waitForResponse(response => response.url().includes('/api/systems/42/correction-targets'));
    assert.deepEqual(errors, []);
    console.log('Browser navigation and almanac passed: categories, combined tree filters, global default, search, paging, platform scope, preserved query, correction platform.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
