"use strict";
// Atelier XYZAC — pilotage de la page. Aucun calcul metier ici : la page
// affiche ce que le serveur rend, et rien d'autre. Si une phrase apparait a
// l'ecran, elle a ete redigee par la session cote Python a partir d'un verdict
// du moteur. Ce fichier ouvre des volets, colore des bordures et compte des
// images.

const $ = (s) => document.querySelector(s);
let etat = null;
let azimut = 35, elevation = 18;
// Angles PROPRES a la vue de surface : tourner la piece pour trouver une
// surface cachee ne doit pas faire tourner la vue de l'etape 2, et
// reciproquement. Deux vues, deux points de vue.
let azimutS = 35, elevationS = 18;
let surfaceChoisie = null;
// Vrai des que l'operateur a clique lui-meme. Tant qu'il ne l'a pas fait, le
// choix par defaut se REEVALUE : la premiere evaluation tombe a un moment ou
// aucune surface n'est encore decidee, et s'y tenir figeait la selection sur
// une ligne qui ne disait rien.
let choixManuel = false;
const diagEnCours = new Set();
let film = { n: 0, i: 0, timer: null, images: [] };

// --------------------------------------------------------- la pagination
//
// Une etape par ecran, et non une longue page qui defile : l'atelier tourne
// sur un ecran de 10 pouces. Sur cinq cartes empilees, quatre etaient
// inaccessibles et remplissaient pourtant tout l'ecran de choses a ignorer.
const PAGES = ["etape-piece", "etape-vue", "etape-verif", "etape-simu",
               "etape-lancer"];
let page = 0;

// Une page est ATTEIGNABLE quand ce qu'elle demande existe. On ne bloque pas
// sur « avoir clique » : un bouton presse dont le calcul a echoue n'a rien
// fait, et l'operateur se retrouverait coince sans savoir pourquoi.
function atteignable(i) {
  if (i === 0) return true;
  return !!(etat && etat.chargee);
}

function allerA(i) {
  const cible = Math.max(0, Math.min(PAGES.length - 1, i));
  if (!atteignable(cible)) return;
  page = cible;
  PAGES.forEach((id, k) => {
    const n = document.getElementById(id);
    if (n) n.classList.toggle("affichee", k === page);
  });
  const m = document.querySelector("main");
  if (m) m.scrollTop = 0;
  if (etat) appliquer();
}

const ETIQUETTES = {
  course_x: "Course X (± mm)", course_y: "Course Y (± mm)",
  course_z_bas: "Z le plus bas (mm)", course_z_haut: "Z le plus haut (mm)",
  a_min: "Bascule A minimum (°)", a_max: "Bascule A maximum (°)",
  rayon_plateau: "Rayon du plateau (mm)",
  diametre_outil: "Diamètre de l'outil (mm)", jauge_outil: "Sortie d'outil (mm)",
};

async function get(url) {
  const r = await fetch(url);
  if (!r.ok && r.status >= 500) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
async function post(url, corps) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corps || {}),
  });
  return r.json();
}

function rafraichirVue() {
  if (!etat || !etat.chargee || etat.rendu) return;
  // l'horodatage force le navigateur a redemander l'image apres un reglage
  $("#image").src = `/api/vue?a=${azimut}&e=${elevation}&t=${Date.now()}`;
}

// ------------------------------------------------------------- chargement

async function envoyerFichier(f) {
  if (!f) return;
  $("#depot").classList.add("occupe");
  try {
    const r = await fetch("/api/televerser", {
      method: "POST", body: f,
      // le nom vient d'un disque quelconque : il est encode ici et nettoye
      // cote serveur, jamais repris tel quel pour ecrire sur le disque
      headers: { "X-Fichier": encodeURIComponent(f.name) },
    });
    etat = await r.json();
  } finally {
    $("#depot").classList.remove("occupe");
  }
  apresChargement();
}

function apresChargement() {
  appliquer();
  rafraichirVue();
  reinitialiserFilm();
  // On avance de soi-meme : la piece est chargee, la seule chose a faire
  // ensuite est de la regarder. Laisser l'operateur chercher le bouton sur un
  // ecran de 10 pouces serait lui donner du travail pour rien.
  if (etat.chargee) allerA(1);
}

// --------------------------------------------------------------- reglages

function dessinerReglages() {
  const c = $("#reglages");
  if (c.dataset.pret === "1") {
    for (const [k, v] of Object.entries(etat.reglages)) {
      const i = c.querySelector(`[name="${k}"]`);
      if (i && document.activeElement !== i) i.value = v;
    }
    return;
  }
  c.innerHTML = "";
  for (const [k, v] of Object.entries(etat.reglages)) {
    const d = document.createElement("div");
    d.className = "champ";
    d.innerHTML = `<label for="r-${k}">${ETIQUETTES[k] || k}</label>
      <input id="r-${k}" name="${k}" type="number" step="any" value="${v}">`;
    c.appendChild(d);
  }
  c.dataset.pret = "1";
  c.addEventListener("change", async (e) => {
    if (e.target.name) {
      etat = await post("/api/reglages", { [e.target.name]: e.target.value });
      appliquer();
      rafraichirVue();
      reinitialiserFilm();
    }
  });
}

// --------------------------------------------------------------- resultats

let derniereVueSurface = "";

function montrerSurface(i) {
  if (i === null || i === undefined || !etat.surfaces[i]) return;
  surfaceChoisie = i;
  document.querySelectorAll("#surfaces li").forEach((li, k) =>
    li.classList.toggle("choisie", k === i));
  // On ne redemande l'image que si la demande a CHANGE. La liste se redessine
  // toutes les 600 ms pendant l'analyse ; horodater chaque appel rechargerait
  // la meme image deux fois par seconde, et elle clignoterait.
  const demande = `i=${i}&a=${azimutS}&e=${elevationS}&r=${etat.revision}`;
  if (demande !== derniereVueSurface) {
    derniereVueSurface = demande;
    $("#image-surface").src = `/api/surface?${demande}`;
  }
  const s = etat.surfaces[i];
  const n = $("#surface-nom");
  n.textContent = `${s.titre} — ${s.etiquette}`;
  n.style.color = s.couleur;
  dessinerDiagnostic(i, s);
}

// « Et avec quel outil, alors ? » — la question que pose tout refus. Elle se
// declenche sur la SELECTION et non sur un bouton : un bouton de plus a
// trouver pour une question qui se pose d'elle-meme est un bouton de trop.
function dessinerDiagnostic(i, s) {
  const d = $("#surface-diag");
  const dispo = (etat.diagnostics || {})[String(i)];
  if (s.verdict === "faisable" || s.verdict === "en-cours") {
    d.hidden = true;
    return;
  }
  d.hidden = false;
  if (dispo) {
    d.textContent = dispo.phrase;
    d.className = "diag" + (dispo.etat === "fait" && dispo.diametre
      ? " outil" : "");
    return;
  }
  d.className = "diag cherche";
  d.textContent = "Recherche de l'outil qui passerait…";
  if (!etat.occupe && !diagEnCours.has(i)) {
    diagEnCours.add(i);
    post("/api/diagnostic", { surface: i }).then((e) => {
      diagEnCours.delete(i);
      etat = e;
      if (surfaceChoisie === i) appliquer();
    });
  }
}

function dessinerResultat() {
  const bloc = $("#resultat");
  if (!etat.surfaces.length) { bloc.hidden = true; surfaceChoisie = null; return; }
  bloc.hidden = false;
  $("#resume").textContent = etat.resume;
  $("#surfaces").innerHTML = etat.surfaces.map((s) => `
    <li class="${s.verdict}">
      <div class="haut">
        <span class="titre">${s.titre}</span>
        <span class="pastille">${s.etiquette}</span>
      </div>
      ${s.consigne ? `<p class="consigne-s">${s.consigne}</p>` : ""}
      ${s.detail ? `<p class="detail">${s.detail}</p>` : ""}
    </li>`).join("");
  $("#avertissements").innerHTML =
    etat.avertissements.map((a) => `<li>${a}</li>`).join("");

  document.querySelectorAll("#surfaces li").forEach((li, k) =>
    li.addEventListener("click", () => { choixManuel = true; montrerSurface(k); }));
  // On en designe une d'office : la premiere qui demande une action, sinon la
  // premiere de la liste. Une vue vide a cote d'une liste ne dit pas qu'elle
  // attend un clic — elle a l'air cassee.
  // Le choix par defaut se REEVALUE tant que l'analyse tourne, puis se fige.
  // Pendant l'analyse, personne ne lit encore : la selection peut se deplacer
  // vers la surface la plus utile a mesure que les verdicts arrivent. Une fois
  // le resultat complet, elle ne bouge plus — deplacer la selection sous les
  // yeux de quelqu'un qui lit est pire que de la laisser sur un choix
  // imparfait.
  if (surfaceChoisie === null || !etat.surfaces[surfaceChoisie]
      || (etat.occupe && !choixManuel)) {
    // La premiere qui demande une action, parmi celles DEJA decidees : en
    // designer une « en analyse » d'office reviendrait a mettre en avant la
    // seule ligne qui ne dit encore rien.
    const ennuyeuse = etat.surfaces.findIndex(
      (s) => s.verdict !== "faisable" && s.verdict !== "en-cours");
    const decidee = etat.surfaces.findIndex((s) => s.verdict !== "en-cours");
    montrerSurface(ennuyeuse >= 0 ? ennuyeuse : (decidee >= 0 ? decidee : 0));
  } else {
    montrerSurface(surfaceChoisie);
  }
}

function appliquer() {
  const chargee = etat.chargee;
  // Le gros bouton s'efface quand son resultat est la : il a servi, et sur
  // l'etape la plus chargee de l'assistant il prenait la place de la liste
  // qu'on vient lire. Un lien discret le remplace.
  $("#verifier").hidden = etat.surfaces.length > 0;
  $("#verifier").disabled = !chargee || etat.occupe;
  $("#simuler").disabled = !chargee || etat.occupe;
  $("#charger").disabled = etat.occupe;
  $("#parcourir").disabled = etat.occupe;

  // Divulgation progressive : une etape qui ne peut rien faire n'est pas
  // grisee, elle est ABSENTE — et son onglet est desactive. Sur 10 pouces,
  // griser quatre etapes remplissait l'ecran de choses a ignorer.
  document.querySelectorAll("[data-requiert='piece']").forEach((s) =>
    s.classList.toggle("verrouille", !chargee));
  if (!chargee && page !== 0) allerA(0);

  const info = $("#piece-info");
  info.hidden = !chargee;
  if (chargee) {
    const source = etat.origine === "votre fichier"
      ? "votre fichier" : "exemple fourni";
    info.innerHTML = `<strong>${etat.piece}</strong>` +
      `<span>${etat.dimensions}</span>` +
      `<span class="jeton">${source}</span>` +
      (etat.import_detail ? `<span class="doux">${etat.import_detail}</span>` : "");
  }

  const p = $("#progres");
  p.hidden = !etat.occupe;
  $("#barre-in").style.width = `${Math.round(etat.progres * 100)}%`;
  $("#etape-texte").textContent = etat.etape || "";

  // Ne balaye QUE les messages poses par ce bloc. Le balayage portait sur
  // « .erreur » tout court, ce qui emportait aussi le bandeau permanent
  // d'absence de rendu : la ligne suivante tombait alors sur un element nul,
  // appliquer() mourait en silence, et plus aucune image ne se rafraichissait.
  // Un selecteur large finit toujours par ramasser un element qu'il ne
  // possede pas.
  document.querySelectorAll(".erreur[data-jetable]").forEach((e) => e.remove());
  if (etat.erreur) {
    // Un refus de chargement s'affiche a l'etape 1, la ou l'utilisateur
    // vient d'agir. L'afficher a l'etape 4 l'obligerait a chercher.
    const d = document.createElement("div");
    d.className = "erreur";
    d.dataset.jetable = "1";
    d.textContent = chargee
      ? `Le calcul s'est arrêté : ${etat.erreur}`
      : `Cette pièce ne peut pas être usinée telle quelle. ${etat.erreur}`;
    (chargee ? $("#etape-verif") : $("#etape-piece")).appendChild(d);
  }

  // Une panne d'affichage 3D se dit a l'ecran, pas seulement dans le
  // terminal : c'est ici que l'utilisateur la subit.
  const sr = $("#sans-rendu");
  sr.hidden = !etat.rendu;
  sr.textContent = etat.rendu || "";
  if (etat.rendu) {
    $("#simuler").disabled = true;
    $("#image").removeAttribute("src");
  }

  // Le gros bouton disparait une fois la simulation faite : il a servi, et
  // sur un ecran de 10 pouces il prenait la place de la vue. Un lien discret
  // le remplace pour recalculer.
  const fait = etat.n_images > 0;
  $("#simuler").hidden = fait;
  $("#simu-resume").hidden = !etat.simulation_resume;
  $("#simu-resume").textContent = etat.simulation_resume || "";
  $("#bloc-note").hidden = !etat.simulation_note;
  $("#simu-note").textContent = etat.simulation_note || "";

  dessinerLegende();
  dessinerFil();
  dessinerReglages();
  dessinerResultat();
}

// La legende vient du SERVEUR, qui la tire de ``ui.debug.palette`` — l'unique
// source du code couleur. La recopier ici aurait cree une deuxieme verite, et
// c'est la copie affichee qui aurait fini par mentir.
function dessinerLegende() {
  if (!etat.legende || !etat.legende.length) return;
  const html = etat.legende.map((l) =>
    `<span><i style="background:${l.couleur}"></i>${l.nom}</span>`).join("");
  for (const cible of ["#legende", "#legende-film"]) {
    const n = $(cible);
    if (n && n.dataset.pret !== "1") { n.innerHTML = html; n.dataset.pret = "1"; }
  }
}

// Le fil d'etapes montre ou l'on en est. Une etape est « faite » quand ce
// qu'elle produit EXISTE — pas quand on l'a cliquee : un bouton presse dont le
// calcul a echoue n'a rien fait.
function dessinerFil() {
  const faites = {
    "etape-piece": etat.chargee,
    "etape-vue": etat.chargee,
    "etape-verif": etat.surfaces.length > 0,
    "etape-simu": etat.n_images > 0,
    "etape-lancer": false,
  };
  document.querySelectorAll("[data-fil]").forEach((b) => {
    const i = PAGES.indexOf(b.dataset.fil);
    b.classList.toggle("faite", !!faites[b.dataset.fil] && i !== page);
    b.classList.toggle("ouverte", i === page);
    b.disabled = !atteignable(i) || etat.occupe;
  });
  const prec = $("#precedent"), suiv = $("#suivant");
  prec.disabled = page === 0;
  suiv.disabled = page === PAGES.length - 1 || !atteignable(page + 1)
    || etat.occupe;
  // Le libelle dit OU l'on va : « Suivant » ne dit rien, et sur un ecran
  // etroit c'est la seule place disponible pour le dire.
  const titres = ["", "Regarder", "Vérifier", "Usinage", "Lancer"];
  suiv.textContent = page + 1 < PAGES.length
    ? `${titres[page + 1]} →` : "Terminé";
}

// --------------------------------------------------------- le battement
//
// Sans lui, un atelier arrete laisse la page telle quelle : tout est encore
// affiche, les boutons sont encore bleus, et plus rien ne repond. Personne ne
// fait le lien entre « j'ai ferme la fenetre noire » et « la page ne fait plus
// rien » — ce sont deux objets differents a l'ecran. Le battement transforme
// un silence en phrase.

let coupe = false;
let battementTimer = null;

function marquerCoupe(estCoupe) {
  if (estCoupe === coupe) return;
  coupe = estCoupe;
  $("#coupe").hidden = !estCoupe;
  document.body.classList.toggle("coupee", estCoupe);
  if (!estCoupe) {
    // L'atelier est revenu. On repart de SON etat, pas de celui qu'on avait
    // garde : entre-temps il a redemarre vide, et afficher une piece qu'il
    // n'a plus serait afficher quelque chose de faux.
    location.reload();
  }
}

async function battre() {
  try {
    const e = await get("/api/etat");
    if (coupe) { marquerCoupe(false); return; }
    // Pendant un calcul, ``sonder`` interroge deja plus souvent : on ne
    // double pas les requetes.
    if (!e.occupe) { etat = e; appliquer(); }
  } catch (err) {
    marquerCoupe(true);
  }
}

function demarrerBattement() {
  if (battementTimer) clearInterval(battementTimer);
  // 4 s : assez rapide pour que « j'ai ferme la fenetre » et « la page le dit »
  // soient percus comme le meme evenement, assez lent pour ne rien couter.
  battementTimer = setInterval(battre, 4000);
}

async function sonder() {
  const avant = etat ? etat.occupe : false;
  try {
    etat = await get("/api/etat");
  } catch (err) {
    // Un calcul interrompu par l'arret de l'atelier ne doit pas laisser la
    // barre de progression tourner dans le vide.
    marquerCoupe(true);
    return;
  }
  appliquer();
  if (etat.occupe) {
    setTimeout(sonder, 600);
  } else if (avant) {
    // un calcul vient de finir
    if (etat.n_images > 0) preparerFilm();
    rafraichirVue();
  }
}

// ------------------------------------------------------------------- film

function reinitialiserFilm() {
  if (film.timer) { clearInterval(film.timer); film.timer = null; }
  film = { n: 0, i: 0, timer: null, images: [] };
  $("#bloc-simu").hidden = true;
  $("#jouer").textContent = "▶";
}

function preparerFilm() {
  film.n = etat.n_images;
  film.images = etat.film || [];
  if (!film.n) return;
  $("#bloc-simu").hidden = false;
  const c = $("#curseur");
  c.max = String(film.n - 1);
  montrer(0);
}

function montrer(i) {
  film.i = ((i % film.n) + film.n) % film.n;
  $("#film").src = `/api/image?i=${film.i}`;
  $("#curseur").value = String(film.i);
  $("#compteur").textContent = `${film.i + 1} / ${film.n}`;
  const f = film.images[film.i];
  if (!f) { $("#axes").innerHTML = ""; $("#film-titre").textContent = ""; return; }
  $("#film-titre").textContent = f.titre;
  const etats = [
    ["X", `${f.x} mm`], ["Y", `${f.y} mm`], ["Z", `${f.z} mm`],
    ["A", `${f.a}°`], ["C", `${f.c}°`],
  ];
  $("#axes").innerHTML =
    etats.map(([k, v]) => `<span class="axe"><b>${k}</b> ${v}</span>`).join("") +
    `<span class="axe axe--etat ${f.coupe ? "axe--coupe" : "axe--rapide"}">` +
    `${f.coupe ? "l'outil coupe" : "déplacement rapide"}</span>` +
    (f.dans_courses ? "" :
      `<span class="axe axe--etat axe--hors">hors des courses réglées</span>`);
}

function jouerPause() {
  if (film.timer) {
    clearInterval(film.timer); film.timer = null;
    $("#jouer").textContent = "▶";
    $("#jouer").title = "Jouer";
    return;
  }
  $("#jouer").textContent = "❚❚";
  $("#jouer").title = "Pause";
  film.timer = setInterval(() => montrer(film.i + 1), 160);
}

// ---------------------------------------------------------------- lancer

function dessinerLancement(l) {
  $("#lancement").hidden = false;
  const bloquantes = l.conditions.filter((c) => c.bloque);
  $("#lancement-resume").textContent = l.possible
    ? "Toutes les conditions sont remplies : un programme peut être préparé."
    : `Pas encore : ${bloquantes.length} condition(s) sur ` +
      `${l.conditions.length} ne sont pas remplies.`;
  $("#conditions").innerHTML = l.conditions.map((c) => `
    <li class="${c.satisfaite ? "ok" : (c.bloque ? "bloque" : "avert")}">
      <div class="titre">${c.satisfaite ? "✔" : "✖"} ${c.titre}</div>
      ${c.satisfaite ? "" : `<p class="consigne-s">${c.action}</p>`}
    </li>`).join("");
}

// ------------------------------------------------------------------ init

async function init() {
  const l = await get("/api/lancement");
  $("#jamais").textContent = l.jamais;

  const ex = await get("/api/exemples");
  $("#exemples").innerHTML = ex.exemples
    .map((e) => `<option value="${e.fichier}">${e.nom}</option>`).join("");
  $("#exemples").value = "C10_dome_convexe.step";

  $("#charger").addEventListener("click", async () => {
    $("#charger").disabled = true;
    etat = await post("/api/piece", { fichier: $("#exemples").value });
    apresChargement();
  });

  // Depot du fichier : glisser-deposer ET bouton. Les deux, parce qu'un
  // glisser-deposer ne s'utilise pas au doigt sur une tablette d'atelier, et
  // qu'un selecteur de fichier ne se devine pas quand on tient deja le fichier.
  const depot = $("#depot");
  ["dragenter", "dragover"].forEach((t) => depot.addEventListener(t, (e) => {
    e.preventDefault(); depot.classList.add("survol");
  }));
  ["dragleave", "drop"].forEach((t) => depot.addEventListener(t, (e) => {
    e.preventDefault(); depot.classList.remove("survol");
  }));
  depot.addEventListener("drop", (e) => {
    const f = e.dataTransfer && e.dataTransfer.files[0];
    if (f) envoyerFichier(f);
  });
  $("#parcourir").addEventListener("click", (e) => {
    e.stopPropagation(); $("#fichier").click();
  });
  depot.addEventListener("click", (e) => {
    if (e.target === depot || e.target.closest(".depot-titre, .depot-icone")) {
      $("#fichier").click();
    }
  });
  depot.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#fichier").click(); }
  });
  $("#fichier").addEventListener("change", (e) => {
    envoyerFichier(e.target.files[0]);
    e.target.value = "";            // pour pouvoir recharger le meme fichier
  });

  document.querySelectorAll("[data-tourne-s]").forEach((b) =>
    b.addEventListener("click", () => {
      azimutS = (azimutS + Number(b.dataset.tourneS) + 360) % 360;
      montrerSurface(surfaceChoisie);
    }));
  document.querySelectorAll("[data-haut-s]").forEach((b) =>
    b.addEventListener("click", () => {
      elevationS = Math.max(-80, Math.min(80, elevationS + Number(b.dataset.hautS)));
      montrerSurface(surfaceChoisie);
    }));

  document.querySelectorAll("[data-tourne]").forEach((b) =>
    b.addEventListener("click", () => {
      azimut = (azimut + Number(b.dataset.tourne) + 360) % 360;
      rafraichirVue();
    }));
  document.querySelectorAll("[data-haut]").forEach((b) =>
    b.addEventListener("click", () => {
      elevation = Math.max(-80, Math.min(80, elevation + Number(b.dataset.haut)));
      rafraichirVue();
    }));

  $("#defaut").addEventListener("click", async () => {
    const kit = { course_x: 150, course_y: 120, course_z_bas: -120,
      course_z_haut: 60, a_min: -120, a_max: 30, rayon_plateau: 75,
      diametre_outil: 6, jauge_outil: 45 };
    etat = await post("/api/reglages", kit);
    appliquer(); rafraichirVue(); reinitialiserFilm();
  });

  const lancerVerification = async () => {
    choixManuel = false; surfaceChoisie = null;
    etat = await post("/api/verifier", {});
    appliquer(); sonder();
  };
  $("#verifier").addEventListener("click", lancerVerification);
  $("#reverifier").addEventListener("click", lancerVerification);

  const lancerSimulation = async () => {
    reinitialiserFilm();
    etat = await post("/api/simuler", { images: 36 });
    appliquer(); sonder();
  };
  $("#resimuler").addEventListener("click", lancerSimulation);
  $("#simuler").addEventListener("click", async () => {
    reinitialiserFilm();
    etat = await post("/api/simuler", { images: 36 });
    appliquer(); sonder();
  });

  $("#lancer").addEventListener("click", async () => {
    dessinerLancement(await get("/api/lancement"));
  });

  $("#precedent").addEventListener("click", () => allerA(page - 1));
  $("#suivant").addEventListener("click", () => allerA(page + 1));
  document.querySelectorAll("[data-fil]").forEach((b) =>
    b.addEventListener("click", () => allerA(PAGES.indexOf(b.dataset.fil))));
  // Fleches du clavier : sur une tablette posee sur un etau, un clavier
  // externe est souvent le seul moyen confortable.
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === "ArrowRight") allerA(page + 1);
    if (e.key === "ArrowLeft") allerA(page - 1);
  });

  $("#jouer").addEventListener("click", jouerPause);
  $("#curseur").addEventListener("input", (e) => montrer(Number(e.target.value)));

  etat = await get("/api/etat");
  allerA(0);
  appliquer();
  demarrerBattement();
}

init();
