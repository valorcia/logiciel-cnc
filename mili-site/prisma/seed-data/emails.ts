/**
 * Default e-mail templates. Editable afterwards in /admin/emails.
 * Body syntax: the small Markdown subset of src/lib/email/render.ts.
 * Nothing here states a specification or a performance of the machine.
 */

export type TemplateSeed = {
  key: string;
  series: "TRANSACTIONAL" | "WELCOME" | "PRELAUNCH" | "LAUNCH";
  name: string;
  locale: string;
  subject: string;
  preheader: string;
  body: string;
};

const PRICE_NOTE = "*$1,499 is a planned introductory price and remains subject to final confirmation.*";

const transactional: TemplateSeed[] = [
  {
    key: "confirm", series: "TRANSACTIONAL", name: "Double opt-in confirmation", locale: "en",
    subject: "Confirm your e-mail to join the MILLI Insider List",
    preheader: "One click and you are in.",
    body: `# One click left.

{{greeting}}

Someone — hopefully you — asked to join the **MILLI Insider List** with this address. Confirm it and you will be among the first to know.

[[Confirm my e-mail|{{confirmUrl}}]]

This link is valid for 7 days. If you did not ask for this, ignore this message: nothing will be sent to you.`,
  },
  {
    key: "confirm", series: "TRANSACTIONAL", name: "Confirmation double opt-in", locale: "fr",
    subject: "Confirmez votre e-mail pour rejoindre la MILLI Insider List",
    preheader: "Un clic et vous y êtes.",
    body: `# Plus qu'un clic.

{{greeting}}

Quelqu'un — vous, espérons-le — a demandé à rejoindre la **MILLI Insider List** avec cette adresse. Confirmez-la et vous serez parmi les premiers informés.

[[Confirmer mon e-mail|{{confirmUrl}}]]

Ce lien est valable 7 jours. Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : rien ne vous sera envoyé.`,
  },
  {
    key: "confirm", series: "TRANSACTIONAL", name: "Double-Opt-in-Bestätigung", locale: "de",
    subject: "Bestätigen Sie Ihre E-Mail für die MILLI Insider List",
    preheader: "Ein Klick, und Sie sind dabei.",
    body: `# Nur noch ein Klick.

{{greeting}}

Jemand – hoffentlich Sie – möchte mit dieser Adresse der **MILLI Insider List** beitreten. Bestätigen Sie die Adresse und Sie erfahren es als Erste.

[[E-Mail bestätigen|{{confirmUrl}}]]

Dieser Link ist 7 Tage gültig. Falls Sie das nicht angefordert haben, ignorieren Sie diese Nachricht: Sie erhalten nichts weiter.`,
  },
  {
    key: "confirm", series: "TRANSACTIONAL", name: "Confirmación de doble opt-in", locale: "es",
    subject: "Confirma tu correo para unirte a la MILLI Insider List",
    preheader: "Un clic y estás dentro.",
    body: `# Solo falta un clic.

{{greeting}}

Alguien — esperamos que tú — ha pedido unirse a la **MILLI Insider List** con esta dirección. Confírmala y estarás entre los primeros en enterarte.

[[Confirmar mi correo|{{confirmUrl}}]]

Este enlace es válido durante 7 días. Si no lo has solicitado, ignora este mensaje: no recibirás nada más.`,
  },
  {
    key: "confirm", series: "TRANSACTIONAL", name: "ダブルオプトイン確認", locale: "ja",
    subject: "MILLI Insider List への登録を確認してください",
    preheader: "ワンクリックで登録完了です。",
    body: `# あとワンクリックです。

{{greeting}}

このアドレスで **MILLI Insider List** への登録リクエストがありました。確認すると、最新情報をいち早くお届けします。

[[メールアドレスを確認する|{{confirmUrl}}]]

このリンクの有効期限は7日間です。お心当たりがない場合は、このメールを無視してください。今後メールが届くことはありません。`,
  },
  {
    key: "already-subscribed", series: "TRANSACTIONAL", name: "Already on the list", locale: "en",
    subject: "You are already on the MILLI Insider List",
    preheader: "Here is your personal link again.",
    body: `# You are already in.

{{greeting}}

This address is already confirmed on the **MILLI Insider List** — nothing else to do.

Your Insider space, with your invitation link and your progress, is here:

[[Open my Insider space|{{insiderLink}}]]`,
  },
  {
    key: "already-subscribed", series: "TRANSACTIONAL", name: "Déjà inscrit", locale: "fr",
    subject: "Vous êtes déjà sur la MILLI Insider List",
    preheader: "Voici à nouveau votre lien personnel.",
    body: `# Vous y êtes déjà.

{{greeting}}

Cette adresse est déjà confirmée sur la **MILLI Insider List** — rien d'autre à faire.

Votre espace Insider, avec votre lien d'invitation et votre progression, est ici :

[[Ouvrir mon espace Insider|{{insiderLink}}]]`,
  },
];

const welcome: TemplateSeed[] = [
  {
    key: "welcome-1", series: "WELCOME", name: "Welcome 1 — Welcome to the MILLI Mystery", locale: "en",
    subject: "Welcome to the MILLI Mystery",
    preheader: "You are in. Here is what happens next.",
    body: `# Welcome to the MILLI Mystery.

{{greeting}}

You are now on the **MILLI Insider List**. Here is what we can tell you today:

- A 5-axis CNC is coming, sold as a kit.
- Its planned introductory price is **$1,499**.
- We will not show the machine before launch day.

Everything else arrives clue by clue. Insiders see each clue first.

[[Open my Insider space|{{insiderLink}}]]

${PRICE_NOTE}`,
  },
  {
    key: "welcome-1", series: "WELCOME", name: "Bienvenue 1 — Bienvenue dans le mystère MILLI", locale: "fr",
    subject: "Bienvenue dans le mystère MILLI",
    preheader: "Vous y êtes. Voici la suite.",
    body: `# Bienvenue dans le mystère MILLI.

{{greeting}}

Vous faites maintenant partie de la **MILLI Insider List**. Voici ce que nous pouvons vous dire aujourd'hui :

- Une CNC 5 axes arrive, vendue en kit.
- Son prix de lancement envisagé est de **1 499 $**.
- Nous ne montrerons pas la machine avant le jour du lancement.

Tout le reste arrive indice par indice. Les Insiders voient chaque indice en premier.

[[Ouvrir mon espace Insider|{{insiderLink}}]]

*1 499 $ est un prix de lancement envisagé, sous réserve de confirmation définitive.*`,
  },
  {
    key: "welcome-1", series: "WELCOME", name: "Willkommen 1", locale: "de",
    subject: "Willkommen beim MILLI Mystery",
    preheader: "Sie sind dabei. So geht es weiter.",
    body: `# Willkommen beim MILLI Mystery.

{{greeting}}

Sie stehen jetzt auf der **MILLI Insider List**. Das können wir Ihnen heute sagen:

- Eine 5-Achs-CNC kommt, als Bausatz.
- Der geplante Einführungspreis liegt bei **1.499 $**.
- Vor dem Launch-Tag zeigen wir die Maschine nicht.

Alles Weitere folgt Hinweis für Hinweis. Insider sehen jeden Hinweis zuerst.

[[Meinen Insider-Bereich öffnen|{{insiderLink}}]]

*1.499 $ ist ein geplanter Einführungspreis, vorbehaltlich endgültiger Bestätigung.*`,
  },
  {
    key: "welcome-1", series: "WELCOME", name: "Bienvenida 1", locale: "es",
    subject: "Bienvenido al misterio MILLI",
    preheader: "Ya estás dentro. Esto es lo que viene.",
    body: `# Bienvenido al misterio MILLI.

{{greeting}}

Ya formas parte de la **MILLI Insider List**. Esto es lo que podemos contarte hoy:

- Llega una CNC de 5 ejes, vendida en kit.
- Su precio de lanzamiento previsto es de **1.499 $**.
- No mostraremos la máquina antes del día del lanzamiento.

Todo lo demás llegará pista a pista. Los Insiders ven cada pista primero.

[[Abrir mi espacio Insider|{{insiderLink}}]]

*1.499 $ es un precio de lanzamiento previsto, sujeto a confirmación definitiva.*`,
  },
  {
    key: "welcome-1", series: "WELCOME", name: "ウェルカム 1", locale: "ja",
    subject: "MILLI Mystery へようこそ",
    preheader: "登録が完了しました。これからの流れをご案内します。",
    body: `# MILLI Mystery へようこそ。

{{greeting}}

**MILLI Insider List** へのご登録ありがとうございます。現時点でお伝えできることは次のとおりです。

- 5軸CNCがキットとして登場します。
- 予定している導入価格は **1,499ドル** です。
- 発売日までマシンの姿は公開しません。

そのほかの情報は、ヒントとして少しずつ公開します。Insider の皆さまには最初にお届けします。

[[Insider スペースを開く|{{insiderLink}}]]

*1,499ドルは予定の導入価格であり、最終確定前のものです。*`,
  },
  {
    key: "welcome-2", series: "WELCOME", name: "Welcome 2 — Why five axes matter", locale: "en",
    subject: "Why five axes matter",
    preheader: "Three axes move the tool. Five axes change what you can make.",
    body: `# Why five axes matter.

{{greeting}}

A 3-axis machine moves a tool left-right, front-back and up-down. It reaches a part from one direction at a time.

Add two rotary axes and the tool can approach the part from almost any angle:

- Undercuts and angled faces become reachable.
- A part that needed several setups can often be cut in fewer.
- Fewer setups means fewer chances to lose your reference.

That is why 5-axis machining is the standard for complex parts — and why it has mostly stayed out of reach for makers.

More soon.`,
  },
  {
    key: "welcome-3", series: "WELCOME", name: "Welcome 3 — The challenge of affordable CNC", locale: "en",
    subject: "The challenge of affordable CNC",
    preheader: "Why 5-axis has stayed expensive, and what we set out to do.",
    body: `# The challenge of affordable CNC.

{{greeting}}

Five-axis machines have stayed expensive for simple reasons: more axes, more mechanics, more software, more things that have to be right at the same time.

MILLI started from a different question: what would a 5-axis CNC look like if it was designed from day one to be built by its owner, as a kit?

We are not going to answer that today. The answer is the machine, and the machine stays hidden until launch day.

What we can share is the target: a planned introductory price of **$1,499**.

${PRICE_NOTE}`,
  },
  {
    key: "welcome-4", series: "WELCOME", name: "Welcome 4 — Invite your friends", locale: "en",
    subject: "Your personal MILLI invitation link",
    preheader: "Bring your friends in. Climb the Insider ranks.",
    body: `# Bring someone in.

{{greeting}}

You have a personal invitation link. Every person who joins through it **and confirms their e-mail** counts for you:

- **3** confirmed friends — MILLI Insider
- **10** confirmed friends — MILLI Pioneer
- **25** confirmed friends — MILLI Founding Member

These are recognition ranks. If perks are attached to them, we will announce them before launch — we do not promise what we have not validated.

Your link: {{referralLink}}

[[See my progress|{{insiderLink}}]]`,
  },
];

function prelaunch(days: number, subject: string, preheader: string, body: string): TemplateSeed {
  return { key: `prelaunch-${days}`, series: "PRELAUNCH", name: `Pre-launch — D-${days}`, locale: "en", subject, preheader, body };
}

const prelaunchSeries: TemplateSeed[] = [
  prelaunch(90, "90 days. The countdown is real.", "MILLI launches on Kickstarter on {{launchDate}}.",
    `# 90 days.

{{greeting}}

The date is set: MILLI launches on Kickstarter on **{{launchDate}}**.

Between now and then, clues will be unlocked on the site. Insiders get them first.

[[Open my Insider space|{{insiderLink}}]]`),
  prelaunch(60, "60 days to MILLI", "Two months. More clues are unlocking.",
    `# 60 days.

{{greeting}}

Two months until **{{launchDate}}**.

New clues are unlocking on the site, and demonstrations are published as soon as they are validated.

[[See the latest clues|{{siteUrl}}]]`),
  prelaunch(30, "30 days to MILLI", "One month left before the reveal.",
    `# One month.

{{greeting}}

In 30 days, on **{{launchDate}}**, we show everything: the machine, the kit, the price.

If someone you know should see this, now is the time to bring them in.

Your link: {{referralLink}}

[[See my progress|{{insiderLink}}]]`),
  prelaunch(14, "Two weeks to MILLI", "14 days. Mark the date.",
    `# Two weeks.

{{greeting}}

MILLI launches on Kickstarter on **{{launchDate}}**.

Launch-day pricing on Kickstarter is usually limited in quantity. Insiders receive the link the moment the campaign opens.`),
  prelaunch(7, "One week to MILLI", "7 days until the reveal.",
    `# One week.

{{greeting}}

Seven days until **{{launchDate}}**.

On launch day you will receive one e-mail with the Kickstarter link. That is the one to open.`),
  prelaunch(3, "3 days to MILLI", "Almost there.",
    `# Three days.

{{greeting}}

On **{{launchDate}}** the mystery ends.

The planned introductory price is **$1,499**.

${PRICE_NOTE}`),
  prelaunch(1, "Tomorrow.", "MILLI launches tomorrow.",
    `# Tomorrow.

{{greeting}}

MILLI launches on Kickstarter **tomorrow, {{launchDate}}**.

Watch your inbox: the link arrives the moment the campaign is live.`),
];

function launch(key: string, name: string, subject: string, preheader: string, body: string): TemplateSeed {
  return { key, series: "LAUNCH", name, locale: "en", subject, preheader, body };
}

const launchSeries: TemplateSeed[] = [
  launch("launch-day", "Launch — Day 0", "MILLI is live on Kickstarter", "The mystery is over. See the machine.",
    `# MILLI is live.

{{greeting}}

The mystery is over. The machine, the full specifications and the contents of the kit are now public.

[[Back MILLI on Kickstarter|{{kickstarterUrl}}]]

Pledges are made on Kickstarter only. Prices, shipping costs and applicable taxes are detailed on the campaign page.`),
  launch("launch-plus-1", "Launch — Day +1", "MILLI: the first 24 hours", "The campaign is open.",
    `# The first day.

{{greeting}}

MILLI has been live on Kickstarter for a day. If you have not seen the machine yet, everything is on the campaign page.

[[See the campaign|{{kickstarterUrl}}]]`),
  launch("launch-plus-7", "Launch — Day +7", "MILLI: one week in", "The campaign is still open.",
    `# One week in.

{{greeting}}

The MILLI campaign has been open for a week. Questions come up every day — the answers are in the campaign FAQ and on our site.

[[See the campaign|{{kickstarterUrl}}]]`),
  launch("launch-plus-30", "Launch — Day +30", "MILLI: the campaign continues", "Still live on Kickstarter.",
    `# The campaign continues.

{{greeting}}

MILLI is still live on Kickstarter.

[[See the campaign|{{kickstarterUrl}}]]`),
  launch("launch-plus-55", "Launch — Day +55", "MILLI: the final days", "The campaign is closing soon.",
    `# The final days.

{{greeting}}

The MILLI Kickstarter campaign is entering its final days. After it closes, campaign pricing ends.

[[Back MILLI on Kickstarter|{{kickstarterUrl}}]]`),
];

export const emailTemplates: TemplateSeed[] = [...transactional, ...welcome, ...prelaunchSeries, ...launchSeries];

const DAY = 24 * 60;

export const emailSteps: { series: "WELCOME" | "PRELAUNCH" | "LAUNCH"; templateKey: string; offsetMinutes: number; sortOrder: number }[] = [
  { series: "WELCOME", templateKey: "welcome-1", offsetMinutes: 0, sortOrder: 1 },
  { series: "WELCOME", templateKey: "welcome-2", offsetMinutes: 2 * DAY, sortOrder: 2 },
  { series: "WELCOME", templateKey: "welcome-3", offsetMinutes: 5 * DAY, sortOrder: 3 },
  { series: "WELCOME", templateKey: "welcome-4", offsetMinutes: 8 * DAY, sortOrder: 4 },
  ...[90, 60, 30, 14, 7, 3, 1].map((d, i) => ({
    series: "PRELAUNCH" as const, templateKey: `prelaunch-${d}`, offsetMinutes: -d * DAY, sortOrder: i + 1,
  })),
  { series: "LAUNCH", templateKey: "launch-day", offsetMinutes: 0, sortOrder: 1 },
  { series: "LAUNCH", templateKey: "launch-plus-1", offsetMinutes: 1 * DAY, sortOrder: 2 },
  { series: "LAUNCH", templateKey: "launch-plus-7", offsetMinutes: 7 * DAY, sortOrder: 3 },
  { series: "LAUNCH", templateKey: "launch-plus-30", offsetMinutes: 30 * DAY, sortOrder: 4 },
  { series: "LAUNCH", templateKey: "launch-plus-55", offsetMinutes: 55 * DAY, sortOrder: 5 },
];
