/** Default public content. Everything is editable in the back office. */

const DAY = 24 * 60 * 60 * 1000;

export function clueSeeds(now: Date) {
  return [
    {
      number: 1, status: "PUBLISHED" as const, publishAt: now,
      title: { en: "The promise", fr: "La promesse", de: "Das Versprechen", es: "La promesa", ja: "約束" },
      content: {
        en: "Five axes. One unexpected price.", fr: "Cinq axes. Un prix inattendu.",
        de: "Fünf Achsen. Ein unerwarteter Preis.", es: "Cinco ejes. Un precio inesperado.", ja: "5軸。そして、予想外の価格。",
      },
    },
    {
      number: 2, status: "SCHEDULED" as const, publishAt: new Date(now.getTime() + 14 * DAY),
      title: { en: "For whom", fr: "Pour qui", de: "Für wen", es: "Para quién", ja: "誰のために" },
      content: {
        en: "Designed for makers.", fr: "Conçue pour les makers.", de: "Für Maker entwickelt.",
        es: "Diseñada para makers.", ja: "メイカーのために設計。",
      },
    },
    {
      number: 3, status: "SCHEDULED" as const, publishAt: new Date(now.getTime() + 28 * DAY),
      title: { en: "The intent", fr: "L'intention", de: "Die Absicht", es: "La intención", ja: "意図" },
      content: {
        en: "Built to challenge expectations.", fr: "Pensée pour bousculer les attentes.",
        de: "Gebaut, um Erwartungen herauszufordern.", es: "Creada para desafiar las expectativas.", ja: "常識に挑むためにつくられた。",
      },
    },
    {
      number: 4, status: "SCHEDULED" as const, publishAt: new Date(now.getTime() + 42 * DAY),
      title: { en: "The format", fr: "Le format", de: "Das Format", es: "El formato", ja: "かたち" },
      content: {
        en: "It arrives as a kit. You build it.", fr: "Elle arrive en kit. Vous la montez.",
        de: "Sie kommt als Bausatz. Sie bauen sie.", es: "Llega en kit. Tú la montas.", ja: "キットで届きます。組み立てるのはあなたです。",
      },
    },
    {
      number: 5, status: "SCHEDULED" as const, publishAt: new Date(now.getTime() + 56 * DAY),
      title: { en: "The wait", fr: "L'attente", de: "Das Warten", es: "La espera", ja: "その日まで" },
      content: {
        en: "Something extraordinary is coming.", fr: "Quelque chose d'extraordinaire arrive.",
        de: "Etwas Außergewöhnliches kommt.", es: "Algo extraordinario está por llegar.", ja: "特別な何かが、やって来る。",
      },
    },
  ];
}

export const faqSeeds = [
  {
    sortOrder: 1, scope: "MYSTERY",
    question: { en: "What is MILI?", fr: "Qu'est-ce que MILI ?", de: "Was ist MILI?", es: "¿Qué es MILI?", ja: "MILI とは何ですか？" },
    answer: {
      en: "MILI is an upcoming 5-axis CNC milling machine sold as a kit. The machine itself stays hidden until launch day.",
      fr: "MILI est une future fraiseuse CNC 5 axes vendue en kit. La machine elle-même reste cachée jusqu'au jour du lancement.",
      de: "MILI ist eine kommende 5-Achs-CNC-Fräse, die als Bausatz verkauft wird. Die Maschine selbst bleibt bis zum Launch-Tag verborgen.",
      es: "MILI es una próxima fresadora CNC de 5 ejes vendida en kit. La máquina permanece oculta hasta el día del lanzamiento.",
      ja: "MILI は、キットとして販売予定の5軸CNCフライス盤です。マシン本体は発売日まで公開しません。",
    },
  },
  {
    sortOrder: 2, scope: "MYSTERY",
    question: { en: "Is $1,499 the final price?", fr: "1 499 $ est-il le prix définitif ?", de: "Ist 1.499 $ der endgültige Preis?", es: "¿Es 1.499 $ el precio definitivo?", ja: "1,499ドルは確定価格ですか？" },
    answer: {
      en: "It is the planned introductory price for the Kickstarter launch and is subject to final confirmation. The confirmed prices, shipping costs and applicable taxes will be published on launch day.",
      fr: "C'est le prix de lancement envisagé pour la campagne Kickstarter, sous réserve de confirmation définitive. Les prix confirmés, les frais de livraison et les taxes applicables seront publiés le jour du lancement.",
      de: "Es ist der geplante Einführungspreis für den Kickstarter-Start, vorbehaltlich endgültiger Bestätigung. Bestätigte Preise, Versandkosten und anfallende Steuern werden am Launch-Tag veröffentlicht.",
      es: "Es el precio de lanzamiento previsto para Kickstarter y está sujeto a confirmación definitiva. Los precios confirmados, los gastos de envío y los impuestos aplicables se publicarán el día del lanzamiento.",
      ja: "Kickstarter での発売時に予定している導入価格であり、最終確定前のものです。確定価格、送料、適用される税金は発売日に公開します。",
    },
  },
  {
    sortOrder: 3, scope: "MYSTERY",
    question: { en: "Why are you not showing the machine?", fr: "Pourquoi ne montrez-vous pas la machine ?", de: "Warum zeigen Sie die Maschine nicht?", es: "¿Por qué no mostráis la máquina?", ja: "なぜマシンを公開しないのですか？" },
    answer: {
      en: "Because its design is what makes the price possible, and we want to reveal it once, completely, on launch day. Until then you get clues, and demonstrations when they are validated.",
      fr: "Parce que c'est sa conception qui rend ce prix possible, et que nous voulons la dévoiler une seule fois, entièrement, le jour du lancement. D'ici là : des indices, et des démonstrations lorsqu'elles sont validées.",
      de: "Weil ihre Konstruktion den Preis möglich macht und wir sie einmal, vollständig, am Launch-Tag enthüllen wollen. Bis dahin gibt es Hinweise und Demonstrationen, sobald sie validiert sind.",
      es: "Porque su diseño es lo que hace posible el precio, y queremos revelarlo una sola vez, por completo, el día del lanzamiento. Hasta entonces habrá pistas y demostraciones cuando estén validadas.",
      ja: "その設計こそがこの価格を可能にしており、発売日に一度にすべてを公開したいからです。それまではヒントと、検証済みのデモをお届けします。",
    },
  },
  {
    sortOrder: 4, scope: "MYSTERY",
    question: { en: "How do I buy one?", fr: "Comment en acheter une ?", de: "Wie kann ich eine kaufen?", es: "¿Cómo puedo comprar una?", ja: "購入方法は？" },
    answer: {
      en: "MILI will launch on Kickstarter, and pledges will be made there only. This site takes no payment and no paid reservation. Join the Insider List to receive the link the moment the campaign opens.",
      fr: "MILI sera lancée sur Kickstarter, et les contributions se feront uniquement là-bas. Ce site ne prend aucun paiement ni aucune réservation payante. Rejoignez l'Insider List pour recevoir le lien dès l'ouverture de la campagne.",
      de: "MILI startet auf Kickstarter, und nur dort kann unterstützt werden. Diese Website nimmt keine Zahlungen und keine kostenpflichtigen Reservierungen an. Tragen Sie sich in die Insider List ein, um den Link beim Start zu erhalten.",
      es: "MILI se lanzará en Kickstarter y las aportaciones se harán únicamente allí. Este sitio no acepta pagos ni reservas de pago. Únete a la Insider List para recibir el enlace en cuanto se abra la campaña.",
      ja: "MILI は Kickstarter で発売され、支援はそこでのみ受け付けます。このサイトでは支払いや有料予約は一切行いません。Insider List に登録すると、キャンペーン開始と同時にリンクをお届けします。",
    },
  },
  {
    sortOrder: 5, scope: "MYSTERY",
    question: { en: "What do you do with my e-mail address?", fr: "Que faites-vous de mon adresse e-mail ?", de: "Was passiert mit meiner E-Mail-Adresse?", es: "¿Qué hacéis con mi correo?", ja: "メールアドレスはどのように使われますか？" },
    answer: {
      en: "We use it to send you MILI news, and only after you confirm it. You can unsubscribe, export or delete your data at any time from your Insider space. We do not sell or share the list.",
      fr: "Nous l'utilisons pour vous envoyer les actualités MILI, et seulement après votre confirmation. Vous pouvez vous désinscrire, exporter ou supprimer vos données à tout moment depuis votre espace Insider. Nous ne vendons ni ne partageons la liste.",
      de: "Wir nutzen sie, um Ihnen MILI-Neuigkeiten zu senden – erst nach Ihrer Bestätigung. Sie können sich jederzeit in Ihrem Insider-Bereich abmelden, Ihre Daten exportieren oder löschen. Wir verkaufen oder teilen die Liste nicht.",
      es: "La usamos para enviarte novedades de MILI, y solo después de que la confirmes. Puedes darte de baja, exportar o eliminar tus datos en cualquier momento desde tu espacio Insider. No vendemos ni compartimos la lista.",
      ja: "確認後にのみ、MILI の最新情報をお送りするために使用します。Insider スペースからいつでも配信停止、データのエクスポート、削除が可能です。リストを販売・共有することはありません。",
    },
  },
];

export const rewardSeeds = [
  { threshold: 3, name: "MILI Insider", description: { en: "Recognition rank. Any perk attached to it will be announced before launch.", fr: "Rang de reconnaissance. Tout avantage associé sera annoncé avant le lancement." } },
  { threshold: 10, name: "MILI Pioneer", description: { en: "Recognition rank. Any perk attached to it will be announced before launch.", fr: "Rang de reconnaissance. Tout avantage associé sera annoncé avant le lancement." } },
  { threshold: 25, name: "MILI Founding Member", description: { en: "Recognition rank. Any perk attached to it will be announced before launch.", fr: "Rang de reconnaissance. Tout avantage associé sera annoncé avant le lancement." } },
];

/** Planned Kickstarter tiers. Seeded INACTIVE: a founder must review and activate them. */
export const pledgeSeeds = [
  { name: "Super Early Bird", priceCents: 149900, sortOrder: 1 },
  { name: "Early Bird", priceCents: 159900, sortOrder: 2 },
  { name: "Special", priceCents: 169900, sortOrder: 3 },
  { name: "Standard", priceCents: 179900, sortOrder: 4 },
  { name: "Final", priceCents: 189900, sortOrder: 5 },
];

/** Empty, unpublished shells of the reveal page sections. Founders write the validated content. */
export const sectionSeeds = [
  { key: "overview", title: { en: "Overview" }, sortOrder: 1 },
  { key: "performance", title: { en: "Performance" }, sortOrder: 2 },
  { key: "materials", title: { en: "Materials" }, sortOrder: 3 },
  { key: "kit", title: { en: "What's in the Kit" }, sortOrder: 4 },
  { key: "assembly", title: { en: "Assembly" }, sortOrder: 5 },
  { key: "software", title: { en: "Software" }, sortOrder: 6 },
  { key: "applications", title: { en: "Applications" }, sortOrder: 7 },
  { key: "shipping", title: { en: "Shipping" }, sortOrder: 8 },
];
