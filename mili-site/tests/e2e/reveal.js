// End-to-end check against a running dev server (npm run dev) with the seeded admin account.
// Run: npm run test:e2e   — uses ADMIN_EMAIL / ADMIN_PASSWORD from the environment, or the .env defaults.
// Mystery/Reveal gate, exercised through the real UI and checked from an anonymous browser.
const { chromium, request } = require('playwright');
const SECRET = 'SECRET-SPINDLE-42', BASE = 'http://localhost:3000';
(async () => {
  const b = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  p.on('pageerror', e => console.log('PAGEERROR', e.message.slice(0, 200)));
  const anon = await request.newContext();
  const leaks = async label => {
    const out = [];
    for (const path of ['/', '/fr', '/mili', '/fr/mili', '/sitemap.xml', '/journal', '/challenge']) {
      const r = await anon.get(BASE + path); const t = await r.text();
      out.push(`${path}=${r.status()}${t.includes(SECRET) ? ' [marker present]' : ''}${/\/mili</.test(t) && path === '/sitemap.xml' ? ' (in sitemap)' : ''}`);
    }
    // RSC payload (what client-side navigation fetches)
    const rsc = await anon.get(BASE + '/mili', { headers: { RSC: '1' } });
    out.push(`rsc/mili=${rsc.status()}${(await rsc.text()).includes(SECRET) ? ' [marker present]' : ''}`);
    console.log(label.padEnd(26), out.join('  '));
  };
  const flash = async () => (await p.$eval('[role=status], [role=alert]:not(.mb-6.rounded-lg.border-\\[\\#ffc46b\\]\\/40)', e => e.textContent).catch(() => '')).slice(0, 110);

  await p.goto(BASE + '/admin/login'); await p.waitForTimeout(1000);
  await p.fill('#email', process.env.ADMIN_EMAIL || 'admin@mili.example'); await p.fill('#password', process.env.ADMIN_PASSWORD || 'change-me-please-123'); await p.click('button[type=submit]'); await p.waitForURL('**/admin');

  // 1. confidential image
  await p.goto(BASE + '/admin/media');
  await p.setInputFiles('#media-file', __dirname + '/fixtures/image.png');
  await p.selectOption('select[name=placement]', 'HERO_IMAGE');
  await p.click('text=Envoyer'); await p.waitForURL('**ok=created**');
  const mediaPath = (await p.$eval('p.select-all', e => e.textContent)).trim();
  console.log('uploaded', mediaPath, '| anon:', (await anon.get(BASE + mediaPath)).status(), '| admin:', (await ctx.request.get(BASE + mediaPath)).status());
  // a non-image renamed .png must be refused
  require('fs').writeFileSync(require('os').tmpdir() + '/mili-fake.png', '<script>alert(1)</script>');
  await p.setInputFiles('#media-file', require('os').tmpdir() + '/mili-fake.png'); await p.click('text=Envoyer'); await p.waitForURL('**error=**');
  console.log('fake image:', decodeURIComponent(p.url().split('error=')[1]).slice(0, 60));

  // 2. product content: a section and a validated spec carrying the secret marker
  await p.goto(BASE + '/admin/product');
  const sec = p.locator('#sections ~ div details').first();
  await sec.locator('summary').click();
  await sec.locator('textarea[name="body.en"]').fill(`The spindle is ${SECRET}.`);
  await sec.locator('input[name=published]').check();
  await sec.locator('button:has-text("Enregistrer")').click(); await p.waitForURL('**ok=saved**');
  const spec = p.locator('details:has-text("Ajouter une caractéristique")');
  if (!(await spec.evaluate(e => e.open))) await spec.locator('summary').click();
  await spec.locator('input[name="label.en"]').fill('Marker'); await spec.locator('input[name="value.en"]').fill(SECRET + ' rpm');
  await spec.locator('input[name=validated]').check();
  await spec.locator('button:has-text("Ajouter")').click(); await p.waitForURL('**ok=saved**');
  await p.goto(BASE + '/admin/reveal/preview');
  console.log('admin preview shows secret:', (await p.content()).includes(SECRET));
  await leaks('MYSTERY (content saved)');

  // 3. reveal: wrong confirmation, then right one
  await p.goto(BASE + '/admin/reveal');
  p.on('dialog', d => d.accept());
  await p.fill('input[name=confirmation]', 'reveal'); await p.check('input[name=understood]'); await p.click('text=Révéler MILI maintenant'); await p.waitForURL('**error=**');
  console.log('wrong word:', decodeURIComponent(p.url().split('error=')[1]).slice(0, 60));
  await p.fill('input[name=confirmation]', 'REVEAL'); await p.check('input[name=understood]'); await p.click('text=Révéler MILI maintenant'); await p.waitForURL('**ok=saved**');
  await leaks('REVEAL');
  console.log('anon media after reveal:', (await anon.get(BASE + mediaPath)).status());
  const pub = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await pub.goto(BASE + '/mili'); await pub.waitForTimeout(1500);
  await pub.goto(BASE + '/'); await pub.waitForTimeout(1500);
  console.log('home h1 in reveal:', await pub.$eval('h1', e => e.textContent));

  // 4. rollback
  await p.goto(BASE + '/admin/reveal');
  await p.fill('input[name=confirmation]', 'MYSTERY'); await p.check('input[name=understood]'); await p.click('text=Repasser en mode Mystery'); await p.waitForURL('**ok=saved**');
  await leaks('back to MYSTERY');
  console.log('anon media after rollback:', (await anon.get(BASE + mediaPath)).status());
  await b.close();
})();
