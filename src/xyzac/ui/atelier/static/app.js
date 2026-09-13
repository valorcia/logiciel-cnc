"use strict";
// Atelier XYZAC — pilotage de la page. Aucun calcul metier ici : la page
// affiche ce que le serveur rend, et rien d'autre. Si une phrase apparait a
// l'ecran, elle a ete redigee par la session cote Python a partir d'un verdict
// du moteur.

const $ = (s) => document.querySelector(s);
let etat = null;
let azimut = 35, elevation = 18;
let film = { n: 0, i: 0, timer: null };

const ETIQUETTES = {
  course_x: "Course X (± mm)", course_y: "Course Y (± mm)",
  course_z_bas: "Z le plus bas (mm)", course_z_haut: "Z le plus haut (mm)",
  a_min: "Bascule A minimum (°)", a_max: "Bascule A maximum (°)",
  rayon_plateau: "Rayon du plateau (mm)",
  diametre_outil: "Diamètre de l'outil (mm)", jauge_outil: "Sortie d'outil (mm)",
};

async function get(url) { const r = await fetch(url); return r.json(); }
async function post(url, corps) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corps || {}),
  });
  return r.json();
}

function rafraichirVue() {
  if (!etat || !etat.chargee) return;
  // l'horodatage force le navigateur a redemander l'image apres un reglage
  $("#image").src = `/api/vue?a=${azimut}&e=${elevation}&t=${Date.now()}`;
}

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
    }
  });
}

function dessinerResultat() {
  const bloc = $("#resultat");
  if (!etat.surfaces.length) { bloc.hidden = true; return; }
  bloc.hidden = false;
  $("#resume").textContent = etat.resume;
  $("#surfaces").innerHTML = etat.surfaces.map((s) => `
    <li class="${s.verdict}">
      <div class="titre">${s.titre}</div>
      <p class="consigne-s">${s.consigne}</p>
      ${s.detail ? `<p class="detail">${s.detail}</p>` : ""}
    </li>`).join("");
  $("#avertissements").innerHTML =
    etat.avertissements.map((a) => `<li>${a}</li>`).join("");
}

function appliquer() {
  const chargee = etat.chargee;
  $("#verifier").disabled = !chargee || etat.occupe;
  $("#simuler").disabled = !chargee || etat.occupe;
  $("#charger").disabled = etat.occupe;

  const info = $("#piece-info");
  info.hidden = !chargee;
  if (chargee) {
    info.innerHTML = `<strong>${etat.piece}</strong> — ${etat.dimensions}` +
      (etat.import_detail ? `<br><span style="color:#99a2b3">${etat.import_detail}</span>` : "");
  }

  const p = $("#progres");
  p.hidden = !etat.occupe;
  $("#barre-in").style.width = `${Math.round(etat.progres * 100)}%`;
  $("#etape-texte").textContent = etat.etape || "";

  document.querySelectorAll(".erreur").forEach((e) => e.remove());
  if (etat.erreur) {
    // Un refus de chargement s'affiche a l'etape 1, la ou l'utilisateur
    // vient d'agir. L'afficher a l'etape 4 l'obligerait a chercher.
    const d = document.createElement("div");
    d.className = "erreur";
    d.textContent = chargee
      ? `Le calcul s'est arrêté : ${etat.erreur}`
      : `Cette pièce ne peut pas être usinée telle quelle. ${etat.erreur}`;
    (chargee ? $("#etape-verif") : $("#etape-piece")).appendChild(d);
  }
  dessinerReglages();
  dessinerResultat();
}

async function sonder() {
  const avant = etat ? etat.occupe : false;
  etat = await get("/api/etat");
  appliquer();
  if (etat.occupe) {
    setTimeout(sonder, 600);
  } else if (avant) {
    // un calcul vient de finir
    if (etat.n_images > 0) preparerFilm();
    rafraichirVue();
  }
}

function preparerFilm() {
  film.n = etat.n_images;
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
}

function jouerPause() {
  if (film.timer) {
    clearInterval(film.timer); film.timer = null;
    $("#jouer").textContent = "▶ jouer";
    return;
  }
  $("#jouer").textContent = "❚❚ pause";
  film.timer = setInterval(() => montrer(film.i + 1), 110);
}

async function init() {
  const ex = await get("/api/exemples");
  $("#exemples").innerHTML = ex.exemples
    .map((e) => `<option value="${e.fichier}">${e.nom}</option>`).join("");
  $("#exemples").value = "C10_dome_convexe.step";

  $("#charger").addEventListener("click", async () => {
    $("#charger").disabled = true;
    etat = await post("/api/piece", { fichier: $("#exemples").value });
    appliquer();
    rafraichirVue();
    $("#etape-vue").scrollIntoView({ behavior: "smooth", block: "start" });
  });

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
    appliquer(); rafraichirVue();
  });

  $("#verifier").addEventListener("click", async () => {
    etat = await post("/api/verifier", {});
    appliquer(); sonder();
  });

  $("#simuler").addEventListener("click", async () => {
    etat = await post("/api/simuler", { images: 24 });
    appliquer(); sonder();
  });

  $("#jouer").addEventListener("click", jouerPause);
  $("#curseur").addEventListener("input", (e) => montrer(Number(e.target.value)));

  etat = await get("/api/etat");
  appliquer();
}

init();
