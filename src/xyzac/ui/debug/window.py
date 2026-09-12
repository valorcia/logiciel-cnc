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

        self._build_toolbar()
        self._build_layers_dock()
        self._build_info_dock()
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

    def _refresh_panels(self) -> None:
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
        for name, rows in pages:
            self.info_tabs.addTab(_kv_table(rows, QtWidgets, QtCore), name)

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
            p = scene_mod.capture(self.state, out, hidden=self.hidden_layers())
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
