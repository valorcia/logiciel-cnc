// End-to-end check against a running dev server: challenge with a file → moderation → public vote → contact form → copy override.
const { chromium } = require('playwright');
const BASE = 'http://localhost:3000';
(async () => {
  const b = await chromium.launch({ args: ['--no-sandbox'] });
  const errors = [];
  const visitor = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  visitor.on('pageerror', e => errors.push(e.message.slice(0, 200)));
  visitor.on('dialog', d => d.accept());
  const RAW = 'RAW-PRIVATE-TEXT turbine blade with undercuts';
  await visitor.goto(BASE + '/challenge'); await visitor.waitForTimeout(2500);
  await visitor.fill('#ch-name', 'Grace Hopper'); await visitor.fill('#ch-email', `grace-${Date.now()}@mili-test.dev`);
  await visitor.fill('#ch-description', RAW);
  await visitor.setInputFiles('#ch-file', __dirname + '/fixtures/image.png');
  await visitor.check('#challenge input[name=consent]'); await visitor.click('#challenge button[type=submit]');
  await visitor.waitForSelector('#challenge [role=status]', { timeout: 10000 });
  console.log('submitted:', await visitor.$eval('#challenge [role=status] h3', e => e.textContent));
  await visitor.reload(); await visitor.waitForTimeout(800);
  console.log('raw text public before moderation:', (await visitor.content()).includes('RAW-PRIVATE-TEXT'));

  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const admin = await ctx.newPage();
  admin.on('dialog', d => d.accept());
  await admin.goto(BASE + '/admin/login'); await admin.waitForTimeout(1000);
  await admin.fill('#email', process.env.ADMIN_EMAIL || 'admin@mili.example'); await admin.fill('#password', process.env.ADMIN_PASSWORD || 'change-me-please-123');
  await admin.click('button[type=submit]'); await admin.waitForURL('**/admin');
  await admin.goto(BASE + '/admin/challenges');
  const fileHref = await admin.$eval('a[href$="/file"]', e => e.getAttribute('href'));
  const file = await ctx.request.get(BASE + fileHref);
  console.log('admin file download:', file.status(), file.headers()['content-disposition'], '| anonymous:', (await visitor.request.get(BASE + fileHref)).status());
  await admin.fill('input[name=publicTitle]', 'A turbine blade'); await admin.fill('textarea[name=publicDescription]', 'Undercuts all around.');
  await admin.click('button[value=approve]'); await admin.waitForURL('**ok=saved**');

  await visitor.goto(BASE + '/challenge'); await visitor.waitForTimeout(1500);
  const html = await visitor.content();
  console.log('public card:', html.includes('A turbine blade'), '| first name only:', html.includes('by Grace') && !html.includes('Hopper'), '| raw text or e-mail public:', html.includes('RAW-PRIVATE-TEXT') || html.includes('mili-test.dev'));
  const vote = visitor.locator('#challenge li:has-text("A turbine blade") button');
  await vote.click(); await visitor.waitForTimeout(1200);
  console.log('after vote:', (await vote.textContent()).replace(/\s+/g, ' '));
  await visitor.reload(); await visitor.waitForTimeout(1500);
  const again = visitor.locator('#challenge li:has-text("A turbine blade") button');
  await again.click(); await visitor.waitForTimeout(1200);
  console.log('second vote, same browser:', (await again.textContent()).replace(/\s+/g, ' '));

  await visitor.goto(BASE + '/contact'); await visitor.waitForTimeout(2500);
  await visitor.selectOption('#ct-kind', 'GDPR_DELETION'); await visitor.fill('#ct-email', 'someone@mili-test.dev'); await visitor.fill('#ct-message', 'Please delete my data, thank you.');
  await visitor.click('form button[type=submit]'); await visitor.waitForSelector('[role=status]', { timeout: 8000 });
  await admin.goto(BASE + '/admin/inquiries');
  console.log('inquiry in back office:', (await admin.content()).includes('someone@mili-test.dev'));

  await admin.goto(BASE + '/admin/content?ns=mystery&locale=en');
  await admin.fill('textarea[name="v:mystery.final"]', 'Patience. Not yet.'); await admin.click('text=Enregistrer cette section'); await admin.waitForURL('**ok=saved**');
  console.log('override live:', (await (await visitor.request.get(BASE + '/')).text()).includes('Patience. Not yet.'));
  await admin.fill('textarea[name="v:mystery.known3"]', 'Planned from nothing'); await admin.click('text=Enregistrer cette section'); await admin.waitForURL('**error=**');
  console.log('override dropping a variable refused:', decodeURIComponent(admin.url().split('error=')[1]).slice(0, 70));
  await admin.goto(BASE + '/admin/content?ns=mystery&locale=en');
  await admin.fill('textarea[name="v:mystery.final"]', ''); await admin.click('text=Enregistrer cette section'); await admin.waitForURL('**ok=saved**');
  console.log('override removed:', (await (await visitor.request.get(BASE + '/')).text()).includes('Not everything is meant to be revealed. Yet.'));
  // clean up
  await admin.goto(BASE + '/admin/challenges?status=APPROVED'); await admin.click('button[value=delete]'); await admin.waitForURL('**ok=**');
  await b.close();
  console.log('errors:', errors.length ? errors : 'none');
})();
