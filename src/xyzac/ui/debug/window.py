"""Fenetre Qt du banc de debug. COQUILLE UNIQUEMENT.

Ce module ne calcule rien et ne construit aucune geometrie : il pose des
widgets, et delegue a ``state`` (ce qui est charge) et ``scene`` (ce qui est
dessine). C'est la regle d'architecture du banc, et elle a une raison pratique
autant que theorique — le conteneur de developpement n'a pas d'ecran, donc tout
ce qui vit ici est intestable. Y mettre de la logique serait y mettre du code
qu'on ne peut pas verifier.

Ce qui est verifiable de ce module : qu'il se construise, que ses cases a cocher
soient reliees aux bons calques, et qu'il se ferme proprement. Ce qui ne l'est
pas depuis ce conteneur : le glisser-deposer de la camera et le rendu dans le
widget. La rotation et le zoom a la souris sont assures par l'interacteur de VTK,
qui n'est pas du code de ce projet ; le banc expose en plus ``orbit`` et
``zoom``, qui sont la meme chose par programme et qui, elles, sont testees.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import palette, scene as scene_mod
from .state import BenchState


def _qt():
    from PySide6 import QtCore, QtGui, QtWidgets

    return QtCore, QtGui, QtWidgets


def _kv_table(rows, QtWidgets, QtCore):
    """Tableau cle/valeur en lecture seule. Aucune saisie : c'est un afficheur."""
    t = QtWidgets.QTableWidget(len(rows), 2)
    t.setHorizontalHeaderLabels(["", ""])
    t.horizontalHeader().setVisible(False)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    t.setShowGrid(False)
    for i, (k, v) in enumerate(rows):
        ki = QtWidgets.QTableWidgetItem(str(k))
        vi = QtWidgets.QTableWidgetItem(str(v))
        if "non disponible" in str(v).lower() or "NON " in str(v):
            vi.setForeground(QtGuiBrush(QtWidgets))
        t.setItem(i, 0, ki)
        t.setItem(i, 1, vi)
    t.resizeColumnsToContents()
    t.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
    return t


def QtGuiBrush(QtWidgets):
    """Pinceau orange pour les valeurs indisponibles.

    Une valeur absente doit se VOIR : c'est la regle de non-invention du projet
    portee a l'affichage. Une case vide se confond avec un zero.
    """
    from PySide6 import QtGui

    return QtGui.QBrush(QtGui.QColor(palette.WARNING))


class DebugWindow:
    """Banc de debug V0. Construit la fenetre et la relie a l'etat.

    Volontairement une classe simple et non une sous-classe de QMainWindow : la
    fenetre est un detail, l'etat est le sujet. Cela permet aussi de construire
    l'objet dans un test sans afficher quoi que ce soit.
    """

    def __init__(self, state: BenchState | None = None, *, interactive: bool = True):
        QtCore, QtGui, QtWidgets = _qt()
        self.state = state or BenchState()
        self.scene: scene_mod.DebugScene | None = None
        self._interactive = bool(interactive)

        self.win = QtWidgets.QMainWindow()
        self.win.setWindowTitle("XYZAC — banc de debug (V0) — SIMULATION")
        self.win.resize(1500, 950)

        # --- vue 3D
        self.interactor = None
        if interactive:
            from pyvistaqt import QtInteractor

            self.interactor = QtInteractor(self.win)
            self.win.setCentralWidget(self.interactor)
        else:
            self.win.setCentralWidget(QtWidgets.QLabel(
                "vue 3D non initialisee (mode non interactif)"))

        self.result = None          # dernier AccessibilityResult
        self._build_toolbar()
        self._build_layers_dock()
        self._build_info_dock()
        self._build_analysis_dock()
        self._refresh_panels()

    # ------------------------------------------------------------------ widgets

    def _build_toolbar(self) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        tb = self.win.addToolBar("Banc")
        tb.setMovable(False)

        self.act_open = tb.addAction("IMPORTER STEP")
        self.act_open.triggered.connect(self.on_open_step)
        tb.addSeparator()
        self.act_reset = tb.addAction("Reinitialiser la vue")
        self.act_reset.triggered.connect(self.on_reset_view)
        self.act_all = tb.addAction("Voir tout")
        self.act_all.triggered.connect(self.on_view_all)
        tb.addSeparator()
        self.act_plan = tb.addAction("CALCULER LA GAMME")
        self.act_plan.setToolTip(
            "Tranche, simule l'enlevement de matiere et valide couche par "
            "couche, puis affiche la trajectoire. Quelques secondes.")
        self.act_plan.triggered.connect(self.on_plan_roughing)
        tb.addSeparator()
        self.act_shot = tb.addAction("CAPTURE DEBUG")
        self.act_shot.triggered.connect(self.on_capture)
        tb.addSeparator()

        lbl = QtWidgets.QLabel("  SIMULATION — aucune liaison machine  ")
        lbl.setStyleSheet(f"color: {palette.WARNING}; font-weight: bold;")
        tb.addWidget(lbl)

    def _build_layers_dock(self) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        dock = QtWidgets.QDockWidget("Calques", self.win)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea)
        tree = QtWidgets.QTreeWidget()
        tree.setHeaderHidden(True)
        self.layer_items: dict[str, object] = {}

        for key, label, declared in scene_mod.LAYERS:
            item = QtWidgets.QTreeWidgetItem([label])
            item.setData(0, QtCore.Qt.UserRole, key)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Checked if declared else QtCore.Qt.Unchecked)
            if not declared:
                item.setDisabled(True)
                item.setText(0, f"{label}  — non disponible")
                item.setToolTip(0, "Aucune source de donnees a ce jalon. "
                                   "L'interface est prevue, le contenu non.")
            tree.addTopLevelItem(item)
            self.layer_items[key] = item

        tree.itemChanged.connect(self._on_layer_toggled)
        self.tree = tree
        dock.setWidget(tree)
        self.win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)

    def _build_info_dock(self) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        dock = QtWidgets.QDockWidget("Etat", self.win)
        dock.setAllowedAreas(QtCore.Qt.RightDockWidgetArea)
        self.info_tabs = QtWidgets.QTabWidget()
        dock.setWidget(self.info_tabs)
        self.win.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.info_dock = dock

    def _refresh_panels(self, candidate=None) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        self.info_tabs.clear()
        st = self.state
        pages = [
            ("Axes", st.axis_readout().lines()),
            ("Machine", st.machine_lines()),
            ("Piece", st.part.lines() if st.part else [("Piece", "aucune")]),
            ("Brut", st.stock_lines()),
            ("Outil", st.tool_lines()),
        ]
        if candidate is not None:
            pages.insert(0, ("Orientation", candidate.lines()))
        if st.plan is not None:
            pages.append(("Gamme", st.plan_lines()))
        if st.part is not None:
            try:
                mat = st.collision_matrix(
                    candidate.direction if candidate is not None else None)
                rows = [(f"{a} / {b}", c) for a, b, c in mat]
            except Exception as exc:                             # noqa: BLE001
                rows = [("Collision", f"non disponible : {exc}")]
            pages.append(("Collision", rows))
        for name, rows in pages:
            self.info_tabs.addTab(_kv_table(rows, QtWidgets, QtCore), name)

    def _build_analysis_dock(self) -> None:
        """Onglet ACCESSIBILITE : le differenciateur du projet, rendu manipulable."""
        QtCore, QtGui, QtWidgets = _qt()
        dock = QtWidgets.QDockWidget("Accessibilite", self.win)
        dock.setAllowedAreas(QtCore.Qt.RightDockWidgetArea
                             | QtCore.Qt.BottomDockWidgetArea)
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)

        form = QtWidgets.QFormLayout()
        self.cb_face = QtWidgets.QComboBox()
        form.addRow("Face", self.cb_face)

        self.cb_tool = QtWidgets.QComboBox()
        self.cb_tool.addItems(["hemispherique (bec rond)", "bout droit"])
        self.cb_tool.currentIndexChanged.connect(self.on_tool_changed)
        form.addRow("Outil", self.cb_tool)

        self.sp_points = QtWidgets.QSpinBox()
        self.sp_points.setRange(1, 200)
        self.sp_points.setValue(8)
        self.sp_points.setToolTip(
            "Points de contact analyses. Environ 70 ms par point : une face "
            "entiere prendrait des minutes. Le rapport dit toujours combien de "
            "points la face contient reellement.")
        form.addRow("Points analyses", self.sp_points)

        self.chk_sing = QtWidgets.QCheckBox("rejeter la singularite A = 0")
        self.chk_sing.setToolTip(
            "Decoche par defaut : la singularite est un probleme de MOUVEMENT, "
            "pas de position. En indexation 3+2 l'axe C est bloque et A = 0 est "
            "utilisable. La rejeter fait declarer inatteignable une face que "
            "trois axes suffisent a usiner.")
        form.addRow("", self.chk_sing)
        lay.addLayout(form)

        self.btn_analyse = QtWidgets.QPushButton("ANALYSER L'ACCESSIBILITE")
        self.btn_analyse.clicked.connect(self.on_analyse)
        lay.addWidget(self.btn_analyse)

        self.lbl_verdict = QtWidgets.QLabel("aucune analyse lancee")
        self.lbl_verdict.setWordWrap(True)
        self.lbl_verdict.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.lbl_verdict)

        self.tbl_summary = QtWidgets.QTableWidget(0, 2)
        self.tbl_summary.horizontalHeader().setVisible(False)
        self.tbl_summary.verticalHeader().setVisible(False)
        self.tbl_summary.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.tbl_summary)

        lay.addWidget(QtWidgets.QLabel("Orientations (cliquer pour placer l'outil)"))
        self.tbl_orient = QtWidgets.QTableWidget(0, 5)
        self.tbl_orient.setHorizontalHeaderLabels(
            ["#", "statut", "A", "C", "marge"])
        self.tbl_orient.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbl_orient.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tbl_orient.itemSelectionChanged.connect(self.on_orientation_selected)
        lay.addWidget(self.tbl_orient)

        dock.setWidget(w)
        self.win.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.analysis_dock = dock

    def _fill_face_combo(self) -> None:
        self.cb_face.clear()
        for idx, stype, area in self.state.face_list():
            self.cb_face.addItem(f"face {idx} — {stype} — {area:.0f} mm2", idx)

    def on_tool_changed(self, *_):
        kind = "endmill" if self.cb_tool.currentIndex() == 1 else "ballnose"
        self.state.set_default_tool(kind)
        self.rebuild_scene()
        self._refresh_panels()
        self.status(f"outil : {self.state.tool.tool_id}")

    def on_analyse(self, *_):
        """ANALYSER L'ACCESSIBILITE : appelle le solveur, affiche le resultat."""
        QtCore, QtGui, QtWidgets = _qt()
        if self.state.part_shape is None:
            self.status("aucune piece chargee")
            return
        face = self.cb_face.currentData()
        if face is None:
            self.status("aucune face selectionnee")
            return
        n = int(self.sp_points.value())
        self.status(f"analyse de la face {face} sur {n} points — "
                    "environ 70 ms par point...")
        QtWidgets.QApplication.processEvents()
        try:
            res = self.state.analyse_face(
                int(face), max_points=n,
                reject_singular=self.chk_sing.isChecked())
        except Exception as exc:                                 # noqa: BLE001
            QtWidgets.QMessageBox.critical(self.win, "Analyse impossible", str(exc))
            self.status(f"analyse impossible : {exc}")
            return
        self.result = res
        self._show_result(res)
        self.rebuild_scene()
        self.status(f"{res.verdict()} — {res.elapsed_s:.2f} s")

    def _show_result(self, res) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        self.lbl_verdict.setText(res.verdict())

        rows = res.summary_lines()
        self.tbl_summary.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.tbl_summary.setItem(i, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.tbl_summary.setItem(i, 1, QtWidgets.QTableWidgetItem(str(v)))
        self.tbl_summary.resizeColumnsToContents()

        # Admissibles en tete, par marge decroissante : la premiere ligne est
        # l'orientation qu'on retiendrait.
        cands = sorted(res.candidates,
                       key=lambda c: (not c.feasible, -c.margin_mm))
        self._ordered = cands
        self.tbl_orient.setRowCount(len(cands))
        for i, c in enumerate(cands):
            col = palette.reason_color(c.reason_name)
            vals = [str(c.index),
                    "ADMISSIBLE" if c.feasible else c.reason_name,
                    f"{c.a_deg:+.2f}", f"{c.c_deg:+.2f}",
                    "—" if not np.isfinite(c.margin_mm) else f"{c.margin_mm:+.3f}"]
            for j, v in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(v)
                it.setForeground(QtGui.QBrush(QtGui.QColor(col)))
                self.tbl_orient.setItem(i, j, it)
        self.tbl_orient.resizeColumnsToContents()

    def on_orientation_selected(self, *_):
        """Place l'outil A l'orientation choisie et detaille ses valeurs."""
        QtCore, QtGui, QtWidgets = _qt()
        if self.result is None or not getattr(self, "_ordered", None):
            return
        rows = self.tbl_orient.selectionModel().selectedRows()
        if not rows:
            return
        cnd = self._ordered[rows[0].row()]
        self.state.set_inspect_from_candidate(self.result, cnd)
        self.rebuild_scene()
        self._refresh_panels(candidate=cnd)
        self.status(f"orientation #{cnd.index} : "
                    + ("ADMISSIBLE" if cnd.feasible else cnd.reason_name))

    # ------------------------------------------------------------------ actions

    def on_open_step(self, *_):
        QtCore, QtGui, QtWidgets = _qt()
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self.win, "Importer un STEP", "", "STEP (*.step *.stp *.STEP *.STP)")
        if path:
            self.load_step(path)

    def load_step(self, path: str | Path) -> None:
        """Charge un STEP et reconstruit la scene. Les erreurs sont MONTREES."""
        QtCore, QtGui, QtWidgets = _qt()
        try:
            self.state.load_step(path)
            self.state.set_default_tool()
        except Exception as exc:                                 # noqa: BLE001
            # Un import qui echoue doit le dire. Le moteur distingue un defaut
            # geometrique d'une invraisemblance de cote, et ce message est la
            # seule chose que l'operateur verra du diagnostic.
            QtWidgets.QMessageBox.critical(
                self.win, "Import STEP refuse", str(exc))
            self.status(f"Import refuse : {exc}")
            return
        self.result = None
        self._fill_face_combo()
        self.rebuild_scene()
        self._refresh_panels()
        self.status(f"{self.state.part.path.name} charge — "
                    f"{self.state.part.n_faces} faces")

    def rebuild_scene(self) -> None:
        if self.interactor is None:
            return
        self.interactor.clear()
        self.scene = scene_mod.build_scene(
            self.state, plotter=self.interactor, off_screen=False)
        tp = self.state.operation_path(0)
        if tp is not None:
            self.scene.add_toolpath(tp[0], tp[1], self.state.machine,
                                    self.state.mount_offset,
                                    self.state.inspect_a_deg,
                                    self.state.inspect_c_deg)
        if self.result is not None:
            self.scene.add_orientations(
                self.result, self.state.machine, self.state.mount_offset,
                self.state.inspect_a_deg, self.state.inspect_c_deg,
                length=scene_mod._arrow_length(self.state))
        self._apply_all_checkboxes()

    def _apply_all_checkboxes(self) -> None:
        QtCore, _, _ = _qt()
        if self.scene is None:
            return
        for key, item in self.layer_items.items():
            on = item.checkState(0) == QtCore.Qt.Checked
            real = self.scene.set_visible(key, on)
            if on and not real:
                # Le calque n'a pas d'acteur : la case ne doit pas rester cochee,
                # sinon elle affirme un affichage qui n'existe pas.
                item.setCheckState(0, QtCore.Qt.Unchecked)
                item.setDisabled(True)

    def _on_layer_toggled(self, item, _col: int) -> None:
        QtCore, _, _ = _qt()
        if self.scene is None:
            return
        key = item.data(0, QtCore.Qt.UserRole)
        self.scene.set_visible(key, item.checkState(0) == QtCore.Qt.Checked)

    def hidden_layers(self) -> set[str]:
        """Calques decoches. C'est ce que la capture doit omettre."""
        QtCore, _, _ = _qt()
        return {k for k, it in self.layer_items.items()
                if it.checkState(0) != QtCore.Qt.Checked}

    def on_reset_view(self, *_):
        if self.scene is not None:
            self.scene.fit_layers("part", "stock", "tool")
            self.interactor.render()

    def on_view_all(self, *_):
        if self.scene is not None:
            self.scene.reset_view()
            self.interactor.render()

    def on_plan_roughing(self, *_):
        """CALCULER LA GAMME : la seule facon de VOIR ce qui serait poste."""
        QtCore, QtGui, QtWidgets = _qt()
        if self.state.part_shape is None:
            self.status("aucune piece chargee")
            return
        self.status("tranchage, simulation de matiere et validation par "
                    "couche — quelques secondes...")
        QtWidgets.QApplication.processEvents()
        try:
            self.state.plan_roughing_preview()
        except Exception as exc:                                 # noqa: BLE001
            QtWidgets.QMessageBox.critical(self.win, "Gamme impossible", str(exc))
            self.status(f"gamme impossible : {exc}")
            return
        self.rebuild_scene()
        self._refresh_panels()
        n = len(self.state.plan.operations) if self.state.plan else 0
        self.status(f"gamme calculee : {n} operation(s) — "
                    "calques « Trajectoire » a gauche")

    def on_capture(self, *_) -> Path | None:
        """CAPTURE DEBUG : image de l'etat courant, par un plotter neuf.

        Passer par ``scene.capture`` et non par une copie d'ecran du widget est
        deliberé : c'est le seul chemin qui donne une image juste avec ou sans
        ecran, et il produit le meme resultat en SSH sur le Raspberry Pi.
        """
        QtCore, QtGui, QtWidgets = _qt()
        if self.state.part is None:
            self.status("Aucune piece chargee : rien a capturer.")
            return None
        out = Path("out") / f"debug_{self.state.part.path.stem}.png"
        self.status("Capture en cours...")
        try:
            p = scene_mod.capture(self.state, out, hidden=self.hidden_layers(),
                                  accessibility=self.result,
                                  toolpath=self.state.operation_path(0))
        except Exception as exc:                                 # noqa: BLE001
            # Un echec doit etre VU, donc modal. Un succes non : on capture
            # souvent sur un banc, et une boite a fermer chaque fois ferait
            # renoncer a s'en servir. Une modale bloque aussi tout test
            # automatique, ce qui est une facon sure de ne jamais verifier le
            # bouton.
            QtWidgets.QMessageBox.critical(self.win, "Capture echouee", str(exc))
            self.status("Capture echouee.")
            return None
        self.status(f"Capture ecrite : {p.resolve()}")
        return p

    def status(self, text: str) -> None:
        """Message non bloquant dans la barre d'etat."""
        self.win.statusBar().showMessage(str(text), 15000)

    # ------------------------------------------------------------------ cycle

    def show(self) -> None:
        self.win.show()

    def close(self) -> None:
        """Fermeture propre : l'interacteur VTK doit partir avant la fenetre.

        Sans cela VTK peut garder une fenetre de rendu ouverte et le processus
        ne rend jamais la main.
        """
        if self.interactor is not None:
            try:
                self.interactor.close()
            except Exception:                                    # noqa: BLE001
                pass
            self.interactor = None
        self.win.close()
