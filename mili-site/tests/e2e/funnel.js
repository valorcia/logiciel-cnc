// End-to-end check against a running dev server (npm run dev) with the seeded admin account.
// Run: npm run test:e2e   — uses ADMIN_EMAIL / ADMIN_PASSWORD from the environment, or the .env defaults.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = require('path').join(__dirname, '..', '..', '.storage', 'outbox');
const mail = (to, re) => { const f = fs.readdirSync(OUT).filter(n => n.includes(to) && n.endsWith('.txt')).sort(); for (const n of f.reverse()) { const m = fs.readFileSync(OUT + '/' + n, 'utf8').match(re); if (m) return m[0]; } return null; };
const subjects = to => fs.readdirSync(OUT).filter(n => n.includes(to) && n.endsWith('.txt')).sort().map(n => fs.readFileSync(OUT + '/' + n, 'utf8').split('\n')[1]);
(async () => {
  const b = await chromium.launch({ args: ['--no-sandbox'] });
  const errors = [];
  const watch = p => { p.on('pageerror', e => errors.push('PAGEERROR ' + e.message)); p.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE ' + m.text().slice(0, 200)); }); return p; };
  async function signup(ctx, email, start) {
    const p = watch(await ctx.newPage());
    await p.goto(start, { waitUntil: 'load' });
    await p.waitForTimeout(2500);
    await p.fill('#join-email', email);
    await p.check('#join input[name=consent]');
    await p.click('#join button[type=submit]');
    await p.waitForSelector('#join [role=status]', { timeout: 8000 });
    await p.waitForTimeout(500);
    return p;
  }
  const stamp = Date.now();
  const a = `ref-${stamp}@mili-test.dev`, f = `friend-${stamp}@mili-test.dev`;
  const ctxA = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const pA = await signup(ctxA, a, 'http://localhost:3000/fr');
  const confirmA = mail(a, /http\S+\/confirm\?token=[\w-]+/);
  console.log('A confirm link:', confirmA && confirmA.replace(/token=.*/, 'token=…'));
  await pA.goto(confirmA); await pA.waitForTimeout(1500);
  console.log('A confirm page:', await pA.$eval('h1', e => e.textContent));
  await pA.goto(confirmA); await pA.waitForTimeout(800);
  console.log('A confirm again:', await pA.$eval('main, body', e => e.innerText.replace(/\s+/g, ' ').slice(0, 160)));
  await pA.click('a[href*="/insider/"]'); await pA.waitForTimeout(2000);
  console.log('A insider url ok:', /\/insider\/MILI-/.test(pA.url()), '| h1:', await pA.$eval('h1', e => e.textContent));
  const invite = await pA.$eval('#insider-link', e => e.value);
  console.log('invite:', invite);
  const insiderUrl = pA.url();
  console.log('A mails:', subjects(a));
  // Friend, separate browser, arrives through the invite link
  const ctxF = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const pF = await signup(ctxF, f, invite + '?utm_source=whatsapp');
  console.log('F landed on:', pF.url().slice(0, 110));
  await pA.reload(); await pA.waitForTimeout(1200);
  console.log('A stats before friend confirms:', await pA.$$eval('dl dd', els => els.map(e => e.textContent)));
  await pF.goto(mail(f, /http\S+\/confirm\?token=[\w-]+/)); await pF.waitForTimeout(1500);
  await pA.reload(); await pA.waitForTimeout(1200);
  console.log('A stats after friend confirms :', await pA.$$eval('dl dd', els => els.map(e => e.textContent)));
  // export + unsubscribe link from e-mail
  const exp = await ctxA.request.get('http://localhost:3000/api/insider/export?t=' + insiderUrl.split('/insider/')[1]);
  console.log('export:', exp.status(), Object.keys(await exp.json()));
  const unsub = mail(a, /http\S+\/unsubscribe\?t=[\w%.-]+/);
  await pA.goto(unsub); await pA.waitForTimeout(1200);
  await pA.click('button.btn-primary'); await pA.waitForTimeout(1500);
  console.log('unsubscribe:', await pA.$eval('[role=status]', e => e.textContent));
  // delete friend data from insider page
  await pF.click('a[href*="/insider/"]'); await pF.waitForTimeout(1500);
  await pF.click('text=/Delete my data/'); await pF.click('text=/Yes, delete everything/'); await pF.waitForTimeout(1500);
  console.log('friend delete:', await pF.$eval('[role=status]', e => e.textContent));
  await b.close();
  console.log('errors:', errors.length ? errors : 'none');
})();
