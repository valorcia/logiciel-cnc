# MILI — plateforme de pré-lancement

Site officiel de la campagne **THE MILI MYSTERY** : page d'accueil cinématographique,
liste d'attente avec double opt-in, parrainage, indices programmés, défis de la
communauté, séquences d'e-mails, journal, et un back-office complet avec la bascule
contrôlée **Mystery → Reveal**.

> Ce dossier (`mili-site/`) vit pour l'instant dans le dépôt `logiciel-cnc`. Il est
> autonome et peut être déplacé dans son propre dépôt (`git subtree split --prefix=mili-site`).

## Ce que fait le site

| Côté visiteur | Côté équipe (`/admin`) |
|---|---|
| Accueil : 5 AXES → $1,499 → IMPOSSIBLE? → MILI IS COMING | Tableau de bord : visiteurs, inscriptions, conversion, sources, pays, campagnes UTM, e-mails |
| Inscription à la *Insider List* (double opt-in) | Prospects : recherche, filtres, export CSV, suppression, parrainages à vérifier |
| Espace Insider : lien de parrainage, rangs, partage, export / suppression de ses données | Textes du site modifiables dans les 5 langues |
| Indices qui s'ouvrent à date fixe | Indices, vidéos de preuve, FAQ, journal, médias |
| Défis : proposition avec fichier joint, galerie modérée, votes | Modération des défis |
| Journal (SEO), pages légales, contact | E-mails : modèles, calendrier, aperçu, envoi de test, historique, statistiques |
| Page produit `/mili` — **inexistante (404) tant que le site est en mode Mystery** | Fiche produit, caractéristiques validées une à une, récompenses, **procédure de révélation** |

Langues : anglais (principale, à la racine), français `/fr`, allemand `/de`, espagnol `/es`, japonais `/ja`.

## Les règles que le code fait respecter

- **La machine n'est jamais montrée avant la révélation.** Le contenu confidentiel n'est
  pas « caché » : il n'est pas envoyé. Tant que le mode est *Mystery*, la page produit répond 404,
  les images marquées confidentielles aussi (même avec leur adresse exacte), et les indices
  non ouverts ne quittent pas le serveur. Vérifié par `tests/integration/reveal.test.ts`
  et `tests/e2e/reveal.js`.
- **Le compte à rebours ne révèle rien.** Seul un Super Admin bascule le site, depuis
  `/admin/reveal`, en tapant `REVEAL`. La bascule est une écriture unique, tracée, réversible.
- **Aucun chiffre inventé.** La fiche produit est livrée vide. Une caractéristique n'est
  publiée qu'après validation par un Super Admin ; une vidéo de preuve aussi. Sans vidéo
  validée, le site affiche un message d'attente neutre.
- **Aucun e-mail marketing sans consentement.** Les séquences ne partent qu'aux adresses
  confirmées dont le consentement est en cours ; chaque e-mail contient un lien de
  désinscription (et l'en-tête « one-click »). Les statistiques viennent uniquement des
  événements transmis par le fournisseur.
- **Aucun paiement.** Les contributions se font sur Kickstarter ; le site n'encaisse rien.
- **$1,499 est un prix envisagé**, toujours accompagné de sa mention, modifiable ou masquable
  dans Paramètres.

## Installation en local

Prérequis : Node.js 22, PostgreSQL 15 ou plus.

```bash
cp .env.example .env          # puis renseigner DATABASE_URL et les deux secrets
npm install
npm run db:deploy             # crée les tables
npm run db:seed               # contenus par défaut + premier Super Admin (ADMIN_EMAIL / ADMIN_PASSWORD)
npm run dev                   # http://localhost:3000  ·  back-office : /admin
```

Sans clé Resend, aucun e-mail ne part. En développement, chaque message est écrit dans
`.storage/outbox/` : ouvrez le fichier `.html` pour cliquer sur le lien de confirmation.

| Commande | Rôle |
|---|---|
| `npm run dev` / `build` / `start` | développement / compilation / production |
| `npm test` | tests unitaires et d'intégration (PostgreSQL réel — base `mili_test`, voir `tests/env.ts`) |
| `npm run test:e2e` | parcours complets dans un navigateur, contre `npm run dev` |
| `npm run lint` · `npm run typecheck` | qualité du code |
| `npm run db:migrate` | créer une migration après modification de `prisma/schema.prisma` |
| `npm run db:deploy` · `npm run db:seed` | appliquer les migrations · installer les contenus par défaut |

## Mise en ligne sur Vercel

1. **Base de données** — créer une base PostgreSQL (Neon, Supabase ou Vercel Postgres) et copier son adresse de connexion.
2. **Stockage de fichiers** — créer un *bucket privé* compatible S3 (Cloudflare R2 recommandé) et une clé d'accès. Obligatoire : Vercel n'a pas de disque persistant, le site refuse d'enregistrer un fichier sans cela.
3. **E-mails** — créer un compte Resend, vérifier le domaine d'envoi (SPF, DKIM, DMARC), créer une clé API, puis un webhook vers `https://VOTRE-DOMAINE/api/webhooks/resend` (tous les événements `email.*`) et copier son secret de signature.
4. **Projet Vercel** — importer le dépôt, régler **Root Directory = `mili-site`**, et saisir les variables de `.env.example` (Production) :
   `DATABASE_URL`, `NEXT_PUBLIC_SITE_URL`, `APP_SECRET`, `BETTER_AUTH_SECRET`, `CRON_SECRET`, `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `EMAIL_FROM`, `STORAGE_DRIVER=s3`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`.
   Générer chaque secret avec `openssl rand -hex 32`. Le site refuse de démarrer en production avec des secrets de développement.
5. **Déployer.** La compilation applique les migrations (`npm run vercel-build`).
6. **Initialiser une seule fois** les contenus et le premier administrateur, depuis votre poste :
   ```bash
   DATABASE_URL="…adresse de production…" ADMIN_EMAIL="vous@…" ADMIN_PASSWORD="…12 caractères min…" npm run db:seed
   ```
   Ne relancez pas cette commande ensuite : elle recrée les contenus par défaut que vous auriez supprimés.
7. **Tâche planifiée** — `vercel.json` appelle `/api/cron/emails` toutes les heures (envoi des séquences, durées de conservation). Une fréquence horaire demande l'offre Vercel Pro ; sur l'offre gratuite, remplacer le calendrier par `5 6 * * *` (une fois par jour).
8. **Dans le back-office**, avant d'annoncer le site : Paramètres (date de lancement, identité légale, adresse postale, réseaux sociaux), relire les pages légales, envoyer un e-mail de test.

### Sauvegardes

Activez les sauvegardes automatiques de votre hébergeur PostgreSQL (restauration à un instant
donné chez Neon et Supabase) et le versionnage du bucket. Le site ne garde rien d'autre.

## Organisation du code

```
messages/            textes du site, un fichier par langue
prisma/              schéma, migrations, contenus par défaut (seed-data/)
src/app/[locale]/    site public
src/app/admin/       back-office (interface en français)
src/app/api/         suivi d'audience, tâche planifiée, webhook e-mail, désinscription
src/components/      composants du site et du back-office
src/lib/             logique : inscriptions, parrainage, e-mails, stockage, sécurité, mode Mystery/Reveal
tests/               unit/ · integration/ · e2e/
```

Technique : Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, PostgreSQL + Prisma 7,
better-auth, Resend, next-intl. Les animations sont en CSS et en JavaScript natif : la bibliothèque
Motion n'a pas été ajoutée, pour tenir les objectifs de vitesse sur mobile.

## Sécurité et données personnelles — en bref

- Back-office : sessions en base, 4 rôles, chaque action vérifiée côté serveur et journalisée ; pas d'inscription publique.
- Formulaires : validation côté serveur, limitation de débit en base, champ piège et jeton horodaté contre les robots, adresses jetables refusées.
- Fichiers : type contrôlé sur le contenu réel (pas sur l'extension), taille limitée, stockage privé, jamais servis depuis un dossier public.
- Jetons de confirmation stockés hachés ; adresses IP jamais conservées en clair ; mesure d'audience sans cookie.
- En-têtes de sécurité (CSP, HSTS, etc.) dans `next.config.ts`.
- RGPD : consentement horodaté et versionné, export et suppression en libre-service, durées de conservation appliquées automatiquement (`src/lib/retention.ts`, à garder alignées avec la politique de confidentialité).

## Limites connues

- Les séquences d'e-mails de bienvenue (2 à 4), de pré-lancement et de lancement n'existent qu'en anglais ; les autres langues reçoivent l'anglais tant qu'une traduction n'est pas ajoutée dans le back-office. Les e-mails de confirmation et de bienvenue n° 1 existent dans les 5 langues.
- Les traductions du site (fr, de, es, ja) et les pages légales (en anglais) doivent être relues par une personne compétente avant le lancement.
- Le stockage S3 est écrit mais n'a pas pu être essayé contre un vrai bucket ; l'envoi par Resend non plus (aucune clé disponible pendant le développement). À vérifier au premier déploiement avec un e-mail de test et un envoi d'image.
- Les prix restent en dollars dans toutes les langues : aucune conversion automatique.
- La vitesse de réaction aux clics (INP) se mesure sur de vrais visiteurs ; elle n'a pas été mesurée ici.
