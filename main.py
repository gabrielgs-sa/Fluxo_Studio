#!/usr/bin/env python3
"""
main.py — editor de fluxogramas para o terminal
=================================================

Usa a biblioteca fluxograma.py (mesma pasta) e guarda o fluxo em um arquivo
.json, que é o que você edita. Do arquivo saem o PDF e o SVG.

    python main.py novo meu_fluxo.json --titulo "Meu fluxo"   cria um fluxo vazio
    python main.py editar fluxo_motor_ads.json                abre o editor interativo
    python main.py gerar  fluxo_motor_ads.json                gera o PDF
    python main.py gerar  fluxo_motor_ads.json -o a.pdf -o a.svg --tema claro --pagina A4
    python main.py listar fluxo_motor_ads.json                mostra etapas e setas

Dentro do editor digite "ajuda" para ver os comandos.
"""

from __future__ import annotations

import argparse
import cmd
import copy
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from fluxograma import DARK, LIGHT, Flowchart

THEMES = {"dark": DARK, "escuro": DARK, "light": LIGHT, "claro": LIGHT}
REL_KEYS = ("below", "above", "right_of", "left_of")
ABS_KEYS = ("cx", "cy", "x", "y")
NODE_KEYS = {"title", "sub", "gap", "dx", "dy", "w", "h", "shape", "style", "tag", *REL_KEYS, *ABS_KEYS}
EDGE_KEYS = {"out", "into", "via", "label", "near", "anchor", "dx", "dy", "at", "dashed"}
RAW_TEXT = {"title", "sub", "label", "tag", "description", "eyebrow"}
SHAPES = {"box", "stadium", "diamond"}
STYLES = {"normal", "alt", "bad", "manual"}
LEGEND_STYLES = STYLES | {"frame"}
ANCHORS = {"top", "bottom", "left", "right"}
ID_RE = re.compile(r"^[A-Za-z_]\w*$")


# --------------------------------------------------------------------------- #
# Arquivo .json  <->  Flowchart
# --------------------------------------------------------------------------- #

def blank_spec(title: str = "") -> dict:
    return {"meta": {"title": title, "eyebrow": "", "description": "", "theme": "dark"},
            "nodes": [], "edges": [], "frames": [], "legend": []}


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    base = blank_spec()
    for k, v in base.items():
        spec.setdefault(k, v)
    return spec


def save_spec(spec: dict, path: Path) -> None:
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate(spec: dict) -> None:
    """Levanta ValueError com mensagem clara se o fluxo estiver inconsistente."""
    seen: list[str] = []
    for n in spec["nodes"]:
        nid = n.get("id", "")
        if not ID_RE.match(nid):
            raise ValueError(f"id inválido '{nid}' (use letras, números e _, sem começar por número)")
        if nid in seen:
            raise ValueError(f"id repetido: {nid}")
        bad = set(n) - NODE_KEYS - {"id"}
        if bad:
            raise ValueError(f"nó {nid}: chave desconhecida {sorted(bad)}. Válidas: {sorted(NODE_KEYS)}")
        if not n.get("title"):
            raise ValueError(f"nó {nid}: falta o título")
        if n.get("shape", "box") not in SHAPES:
            raise ValueError(f"nó {nid}: forma deve ser {sorted(SHAPES)}")
        if n.get("style", "normal") not in STYLES:
            raise ValueError(f"nó {nid}: estilo deve ser {sorted(STYLES)}")
        seen.append(nid)
    ids = set(seen)
    for n in spec["nodes"]:
        for k in REL_KEYS:
            if n.get(k) is not None and n[k] not in ids:
                raise ValueError(f"nó {n['id']}: {k}={n[k]} não existe")
    ordered_nodes(spec["nodes"])  # detecta referência circular
    for e in spec["edges"]:
        for end in ("src", "dst"):
            if e.get(end) not in ids:
                raise ValueError(f"seta {e.get('src')}→{e.get('dst')}: nó '{e.get(end)}' não existe")
        bad = set(e) - EDGE_KEYS - {"src", "dst"}
        if bad:
            raise ValueError(f"seta {e['src']}→{e['dst']}: chave desconhecida {sorted(bad)}. Válidas: {sorted(EDGE_KEYS)}")
        if e.get("near", "mid") not in ("start", "mid", "end"):
            raise ValueError("near deve ser start, mid ou end")
        for k in ("out", "into"):
            v = e.get(k)
            if isinstance(v, str) and v not in ANCHORS:
                raise ValueError(f"seta {e['src']}→{e['dst']}: {k} deve ser top/bottom/left/right ou [x, y]")
    for fr in spec["frames"]:
        for m in fr["around"]:
            if m not in ids:
                raise ValueError(f"moldura '{fr['label']}': nó '{m}' não existe")
        if not fr["around"]:
            raise ValueError(f"moldura '{fr['label']}' está sem nós")
    for style, _ in spec["legend"]:
        if style not in LEGEND_STYLES:
            raise ValueError(f"legenda: estilo '{style}' inválido ({sorted(LEGEND_STYLES)})")
    if spec["meta"].get("theme", "dark") not in THEMES:
        raise ValueError("tema deve ser dark/escuro ou light/claro")


def ordered_nodes(nodes: list) -> list:
    """Ordena para que cada nó venha depois do nó em que ele se apoia (below=, right_of=...)."""
    byid, state, done = {n["id"]: n for n in nodes}, {}, []

    def visit(n, stack):
        st = state.get(n["id"])
        if st == 2:
            return
        if st == 1:
            raise ValueError("posições em círculo: " + " → ".join(stack + [n["id"]]))
        state[n["id"]] = 1
        for k in REL_KEYS:
            if n.get(k) is not None:
                visit(byid[n[k]], stack + [n["id"]])
        state[n["id"]] = 2
        done.append(n)

    for n in nodes:
        visit(n, [])
    return done


def _coord(v, nodes):
    """Número, ou expressão como "pede.cx + 20" usando as caixas já posicionadas."""
    if isinstance(v, (int, float)):
        return float(v)
    return float(eval(str(v), {"__builtins__": {}}, dict(nodes)))


def _point(p, nodes):
    return (_coord(p[0], nodes), _coord(p[1], nodes))


def build(spec: dict, theme: str | None = None) -> Flowchart:
    validate(spec)
    meta = spec["meta"]
    f = Flowchart(title=meta.get("title", ""), eyebrow=meta.get("eyebrow", ""),
                  description=meta.get("description", ""), theme=THEMES[theme or meta.get("theme", "dark")])
    for n in ordered_nodes(spec["nodes"]):
        kw = {k: v for k, v in n.items() if k not in ("id", "title", "sub")}
        f.node(n["id"], n["title"], n.get("sub", ""), **kw)
    for e in spec["edges"]:
        kw = {k: v for k, v in e.items() if k not in ("src", "dst")}
        if "via" in kw:
            kw["via"] = [_point(p, f.nodes) for p in kw["via"]]
        for k in ("into", "out"):
            if isinstance(kw.get(k), (list, tuple)):
                kw[k] = _point(kw[k], f.nodes)
        if kw.get("at"):
            kw["at"] = _point(kw["at"], f.nodes)
        f.edge(e["src"], e["dst"], **kw)
    for fr in spec["frames"]:
        f.frame(fr["label"], fr["around"], pad=tuple(fr.get("pad", (25, 24))), label_dy=fr.get("label_dy", 24))
    f.legend(*[tuple(x) for x in spec["legend"]])
    return f


def render(spec: dict, out: Path, theme: str | None = None, page: str = "auto") -> None:
    f = build(spec, theme)
    if out.suffix.lower() == ".pdf":
        f.save(str(out), page=page)
    else:
        f.save(str(out))


# --------------------------------------------------------------------------- #
# Editor interativo
# --------------------------------------------------------------------------- #

def coerce(key: str, v: str):
    if key in RAW_TEXT:
        return v
    if v.lower() in ("none", "null", "-"):
        return None
    try:
        return json.loads(v)
    except ValueError:
        return v


class Editor(cmd.Cmd):
    intro = "Editor de fluxogramas. Digite 'ajuda' para ver os comandos, 'sair' para sair."

    def __init__(self, path: Path, spec: dict, auto: bool = False):
        super().__init__()
        self.path, self.spec = path, spec
        self.undo: list[dict] = []
        self.dirty = False
        self.auto = auto
        self.last_out = path.with_suffix(".pdf")
        self.prompt = f"{path.stem}> "

    # ---- infraestrutura ---------------------------------------------------- #

    def mutate(self, fn) -> bool:
        snap = copy.deepcopy(self.spec)
        try:
            fn()
            build(self.spec)  # valida e testa o layout
        except Exception as ex:  # noqa: BLE001
            self.spec = snap
            print(f"  ✗ {ex}  (nada foi alterado)")
            return False
        self.undo = (self.undo + [snap])[-100:]
        self.dirty = True
        if self.auto:
            self._render(self.last_out, quiet=True)
        return True

    def _render(self, out: Path, theme=None, page="auto", quiet=False) -> None:
        try:
            render(self.spec, out, theme, page)
            self.last_out = out
            if not quiet:
                print(f"  ✓ gerado: {out}")
        except Exception as ex:  # noqa: BLE001
            print(f"  ✗ {ex}")

    @staticmethod
    def parse(arg: str):
        pos, kv = [], {}
        for t in shlex.split(arg):
            m = re.match(r"^([A-Za-z_]\w*)=(.*)$", t, re.S)
            if m:
                kv[m.group(1)] = m.group(2)
            else:
                pos.append(t)
        return pos, kv

    def node_of(self, nid: str) -> dict:
        for n in self.spec["nodes"]:
            if n["id"] == nid:
                return n
        raise ValueError(f"nó '{nid}' não existe")

    def edges_of(self, a: str, b: str) -> list:
        return [e for e in self.spec["edges"] if e["src"] == a and e["dst"] == b]

    def onecmd(self, line):
        try:
            return super().onecmd(line)
        except ValueError as ex:  # erros de uso, ex.: json inválido
            print(f"  ✗ {ex}")
        return False

    def emptyline(self):
        return False

    def default(self, line):
        print(f"  comando desconhecido: {line.split()[0]}  (digite 'ajuda')")

    # ---- comandos ---------------------------------------------------------- #

    def do_listar(self, arg):
        """listar — mostra etapas (com posição calculada), setas, molduras e legenda."""
        try:
            f = build(self.spec)
        except Exception as ex:  # noqa: BLE001
            print(f"  ✗ {ex}")
            return
        print(f"\n  {self.spec['meta'].get('title') or '(sem título)'}   [{self.spec['meta'].get('theme', 'dark')}]")
        print("\n  ETAPAS  (id · forma/estilo · x,y · l×a · posição)")
        for n in self.spec["nodes"]:
            c = f.nodes[n["id"]]
            rel = next((f"{k}={n[k]}" for k in REL_KEYS if n.get(k)), "absoluta")
            extra = f" gap={n['gap']}" if "gap" in n and rel != "absoluta" else ""
            print(f"   {n['id']:<10} {n.get('shape', 'box'):<8} {n.get('style', 'normal'):<7} "
                  f"{c.x:6.0f},{c.y:<6.0f} {c.w:4.0f}×{c.h:<4.0f} {rel}{extra}   “{n['title']}”")
        print("\n  SETAS")
        for e in self.spec["edges"]:
            extra = " ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in e.items() if k not in ("src", "dst"))
            print(f"   {e['src']} → {e['dst']}   {extra}")
        for fr in self.spec["frames"]:
            print(f"\n  MOLDURA “{fr['label']}”: {', '.join(fr['around'])}")
        if self.spec["legend"]:
            print("\n  LEGENDA: " + " | ".join(f"{s}: {t}" for s, t in self.spec["legend"]))
        print()

    do_ls = do_listar

    def do_no(self, arg):
        """no ID "Título" ["Subtítulo"] [chave=valor ...]
        Cria uma etapa. Sem posição, entra abaixo da última etapa (gap=44).
        Chaves: below= above= right_of= left_of= gap= w= h= dx= dy= cx= cy= x= y=
                shape=box|stadium|diamond  style=normal|alt|bad|manual  tag="Texto"
        Ex.: no analise "Analisa o caso" "leitura manual" right_of=confirma gap=50 style=manual"""
        pos, kv = self.parse(arg)
        if len(pos) < 2 or len(pos) > 3:
            return print('  uso: no ID "Título" ["Subtítulo"] [chave=valor ...]')

        def run():
            if any(n["id"] == pos[0] for n in self.spec["nodes"]):
                raise ValueError(f"já existe um nó '{pos[0]}' (use 'editar')")
            n = {"id": pos[0], "title": pos[1]}
            if len(pos) == 3:
                n["sub"] = pos[2]
            for k, v in kv.items():
                n[k] = coerce(k, v)
            if not any(k in n for k in (*REL_KEYS, *ABS_KEYS)):
                if self.spec["nodes"]:
                    n.update(below=self.spec["nodes"][-1]["id"], gap=44)
                else:
                    n.update(cx=300, y=0)
            self.spec["nodes"].append(n)

        if self.mutate(run):
            print(f"  ✓ etapa '{pos[0]}' criada")

    do_node = do_no

    def do_seta(self, arg):
        """seta ORIGEM DESTINO ["rótulo"] [chave=valor ...]
        Chaves: out= into= (top|bottom|left|right ou [x,y])  near=start|mid|end  anchor=start|middle|end
                dx= dy= at=[x,y]  dashed=true  via=[[x,y],...]
        Em via/into/at, as coordenadas aceitam expressões: via=[["pede.cx", "aut.bottom+16"]]
        Ex.: seta ads reprova Reprovada near=end"""
        pos, kv = self.parse(arg)
        if len(pos) not in (2, 3):
            return print('  uso: seta ORIGEM DESTINO ["rótulo"] [chave=valor ...]')

        def run():
            e = {"src": pos[0], "dst": pos[1]}
            if len(pos) == 3:
                e["label"] = pos[2]
            for k, v in kv.items():
                e[k] = coerce(k, v)
            self.spec["edges"].append(e)

        if self.mutate(run):
            print(f"  ✓ seta {pos[0]} → {pos[1]}")

    do_edge = do_seta

    def do_editar(self, arg):
        """editar ID chave=valor ...   (title= sub= shape= style= tag= w= h= gap= below= ...)
        Use chave=none para apagar um campo. Ao trocar below/above/right_of/left_of a posição
        antiga é substituída. Ex.: editar confirma sub="e proposta ao cliente" gap=60"""
        pos, kv = self.parse(arg)
        if len(pos) != 1 or not kv:
            return print("  uso: editar ID chave=valor ...")

        def run():
            n = self.node_of(pos[0])
            for k, v in kv.items():
                if k == "id":
                    raise ValueError("para mudar o id use 'renomear'")
                val = coerce(k, v)
                if k in (*REL_KEYS, *ABS_KEYS) and val is not None:
                    for other in (*REL_KEYS, *ABS_KEYS):
                        n.pop(other, None)
                if val is None:
                    n.pop(k, None)
                else:
                    n[k] = val

        if self.mutate(run):
            print(f"  ✓ '{pos[0]}' atualizado")

    do_set = do_editar

    def do_editarseta(self, arg):
        """editarseta ORIGEM DESTINO chave=valor ...   (label= near= out= into= via= dx= dy= ...)
        Se houver mais de uma seta entre o par, todas são alteradas. chave=none apaga."""
        pos, kv = self.parse(arg)
        if len(pos) != 2 or not kv:
            return print("  uso: editarseta ORIGEM DESTINO chave=valor ...")

        def run():
            es = self.edges_of(*pos)
            if not es:
                raise ValueError(f"não há seta {pos[0]} → {pos[1]}")
            for e in es:
                for k, v in kv.items():
                    val = coerce(k, v)
                    e.pop(k, None) if val is None else e.__setitem__(k, val)

        if self.mutate(run):
            print("  ✓ seta atualizada")

    def do_remover(self, arg):
        """remover no ID | seta ORIGEM DESTINO | moldura "Rótulo" | legenda "texto"
        Remover um nó apaga as setas ligadas a ele; não remove se outro nó usa ele como posição."""
        pos, _ = self.parse(arg)
        if len(pos) < 2:
            return print("  uso: remover no|seta|moldura|legenda ...")
        kind, rest = pos[0], pos[1:]

        def run():
            if kind in ("no", "node"):
                nid = rest[0]
                self.node_of(nid)
                deps = [n["id"] for n in self.spec["nodes"] if any(n.get(k) == nid for k in REL_KEYS)]
                if deps:
                    raise ValueError(f"'{', '.join(deps)}' usa '{nid}' como referência de posição; "
                                     f"reposicione com 'editar' antes (ex.: editar {deps[0]} below=OUTRO)")
                self.spec["nodes"] = [n for n in self.spec["nodes"] if n["id"] != nid]
                before = len(self.spec["edges"])
                self.spec["edges"] = [e for e in self.spec["edges"] if nid not in (e["src"], e["dst"])]
                print(f"  ({before - len(self.spec['edges'])} seta(s) removida(s) junto)")
                for fr in self.spec["frames"]:
                    fr["around"] = [m for m in fr["around"] if m != nid]
                self.spec["frames"] = [fr for fr in self.spec["frames"] if fr["around"]]
            elif kind in ("seta", "edge") and len(rest) == 2:
                if not self.edges_of(*rest):
                    raise ValueError(f"não há seta {rest[0]} → {rest[1]}")
                self.spec["edges"] = [e for e in self.spec["edges"] if (e["src"], e["dst"]) != tuple(rest)]
            elif kind == "moldura":
                n0 = len(self.spec["frames"])
                self.spec["frames"] = [fr for fr in self.spec["frames"] if fr["label"] != rest[0]]
                if len(self.spec["frames"]) == n0:
                    raise ValueError("moldura não encontrada")
            elif kind == "legenda":
                n0 = len(self.spec["legend"])
                self.spec["legend"] = [x for x in self.spec["legend"] if x[1] != rest[0]]
                if len(self.spec["legend"]) == n0:
                    raise ValueError("item de legenda não encontrado")
            else:
                raise ValueError("uso: remover no ID | seta A B | moldura \"Rótulo\" | legenda \"texto\"")

        if self.mutate(run):
            print("  ✓ removido")

    do_rm = do_remover

    def do_renomear(self, arg):
        """renomear ID_ANTIGO ID_NOVO — troca o id em todas as referências."""
        pos, _ = self.parse(arg)
        if len(pos) != 2:
            return print("  uso: renomear ID_ANTIGO ID_NOVO")
        old, new = pos

        def run():
            if any(n["id"] == new for n in self.spec["nodes"]):
                raise ValueError(f"já existe '{new}'")
            self.node_of(old)
            pat = re.compile(rf"\b{re.escape(old)}\b(?=\.)")
            fix = lambda v: pat.sub(new, v) if isinstance(v, str) else v  # noqa: E731
            for n in self.spec["nodes"]:
                if n["id"] == old:
                    n["id"] = new
                for k in REL_KEYS:
                    if n.get(k) == old:
                        n[k] = new
            for e in self.spec["edges"]:
                e["src"] = new if e["src"] == old else e["src"]
                e["dst"] = new if e["dst"] == old else e["dst"]
                for k in ("via", "into", "at"):
                    if isinstance(e.get(k), list):
                        e[k] = [[fix(c) for c in p] if isinstance(p, list) else fix(p) for p in e[k]]
            for fr in self.spec["frames"]:
                fr["around"] = [new if m == old else m for m in fr["around"]]

        if self.mutate(run):
            print(f"  ✓ '{old}' → '{new}'")

    def do_moldura(self, arg):
        """moldura "Rótulo" ID ID ... [pad=[25,24]] — desenha moldura tracejada em volta das etapas.
        Se já existir moldura com esse rótulo, ela é substituída."""
        pos, kv = self.parse(arg)
        if len(pos) < 2:
            return print('  uso: moldura "Rótulo" ID ID ... [pad=[25,24]]')

        def run():
            fr = {"label": pos[0], "around": pos[1:]}
            if "pad" in kv:
                fr["pad"] = coerce("pad", kv["pad"])
            self.spec["frames"] = [x for x in self.spec["frames"] if x["label"] != pos[0]] + [fr]

        if self.mutate(run):
            print("  ✓ moldura definida")

    def do_legenda(self, arg):
        """legenda ESTILO "texto" | legenda limpar — ESTILO: normal, alt, manual, bad, frame"""
        pos, _ = self.parse(arg)

        def run():
            if pos == ["limpar"]:
                self.spec["legend"] = []
            elif len(pos) == 2:
                self.spec["legend"].append([pos[0], pos[1]])
            else:
                raise ValueError('uso: legenda ESTILO "texto"  |  legenda limpar')

        if self.mutate(run):
            print("  ✓ legenda atualizada")

    def do_meta(self, arg):
        """meta chave=valor ... — title=, eyebrow=, description=, theme=dark|light
        Ex.: meta title="Fluxo do motor ADS" theme=light"""
        _, kv = self.parse(arg)
        if not kv or set(kv) - {"title", "eyebrow", "description", "theme"}:
            return print("  uso: meta title=... eyebrow=... description=... theme=dark|light")

        def run():
            self.spec["meta"].update(kv)

        if self.mutate(run):
            print("  ✓ cabeçalho atualizado")

    def do_desfazer(self, arg):
        """desfazer — volta a última alteração."""
        if not self.undo:
            return print("  nada para desfazer")
        self.spec = self.undo.pop()
        self.dirty = True
        print("  ✓ desfeito")
        if self.auto:
            self._render(self.last_out, quiet=True)

    do_undo = do_desfazer

    def do_gerar(self, arg):
        """gerar [arquivo.pdf|arquivo.svg] [theme=light] [page=A4] — padrão: <nome>.pdf ao lado do .json."""
        pos, kv = self.parse(arg)
        out = Path(pos[0]) if pos else self.path.with_suffix(".pdf")
        self._render(out, kv.get("theme"), kv.get("page", "auto"))

    do_render = do_gerar

    def do_auto(self, arg):
        """auto on|off — gera o PDF de novo a cada alteração (deixe-o aberto num leitor que recarrega)."""
        self.auto = arg.strip().lower() in ("on", "sim", "1", "")
        print(f"  auto-geração {'ligada' if self.auto else 'desligada'} → {self.last_out}")
        if self.auto:
            self._render(self.last_out, quiet=True)

    def do_abrir(self, arg):
        """abrir — gera e abre o PDF no visualizador do sistema."""
        self._render(self.last_out)
        if sys.platform.startswith("win"):
            os.startfile(self.last_out)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(self.last_out)])

    def do_salvar(self, arg):
        """salvar — grava o .json."""
        save_spec(self.spec, self.path)
        self.dirty = False
        print(f"  ✓ salvo: {self.path}")

    do_save = do_salvar

    def do_ajuda(self, arg):
        """ajuda [comando]"""
        if arg.strip():
            return self.do_help(arg)
        print("""
  listar                            mostra etapas, setas, molduras, legenda
  no ID "Título" ["Sub"] [chaves]   cria etapa (sem posição: abaixo da última)
  seta A B ["rótulo"] [chaves]      liga duas etapas
  editar ID chave=valor ...         altera etapa (chave=none apaga)
  editarseta A B chave=valor ...    altera seta
  remover no|seta|moldura|legenda   remove
  renomear ANTIGO NOVO              troca id
  moldura "Rótulo" ID ID ...        moldura tracejada
  legenda ESTILO "texto" | limpar
  meta title=... theme=light
  desfazer
  gerar [arq.pdf|svg] [theme=light] [page=A4]
  auto on|off                       regera o PDF a cada alteração
  abrir                             gera e abre o PDF
  salvar / sair
  'ajuda COMANDO' mostra os detalhes (chaves aceitas etc.)
""")

    do_help_pt = do_ajuda

    def do_sair(self, arg):
        """sair — pergunta se quer salvar caso haja alterações."""
        if self.dirty:
            try:
                r = input("  Salvar alterações antes de sair? [S/n] ").strip().lower()
            except EOFError:
                r = "s"
            if r in ("", "s", "sim", "y"):
                self.do_salvar("")
        return True

    do_quit = do_exit = do_EOF = do_sair

    def get_names(self):  # faz 'help'/'ajuda' listar só os comandos em português
        return [n for n in super().get_names() if n != "do_help_pt"]


# --------------------------------------------------------------------------- #
# Linha de comando
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].endswith(".json"):  # atalho: python fluxo.py arquivo.json
        argv.insert(0, "editar")

    ap = argparse.ArgumentParser(prog="fluxo", description="Editor de fluxogramas no terminal e na interface gráfica.")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("novo", help="cria um arquivo de fluxo vazio")
    p.add_argument("arquivo")
    p.add_argument("--titulo", default="")

    p = sub.add_parser("editar", help="abre o editor interativo (cria o arquivo se não existir)")
    p.add_argument("arquivo")
    p.add_argument("--auto", action="store_true", help="regera o PDF a cada alteração")

    p = sub.add_parser("gerar", help="gera PDF/SVG a partir do .json")
    p.add_argument("arquivo")
    p.add_argument("-o", "--saida", action="append", help="arquivo de saída (.pdf/.svg); pode repetir")
    p.add_argument("--tema", choices=sorted(THEMES), help="sobrescreve o tema do arquivo")
    p.add_argument("--pagina", default="auto", help='"auto" (padrão), A4, A3, LETTER...')

    p = sub.add_parser("listar", help="mostra etapas e setas")
    p.add_argument("arquivo")

    p = sub.add_parser("gui", aliases=["interface"], help="abre o editor gráfico interativo")
    p.add_argument("arquivo", nargs="?", default="fluxo.json")

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0

    path = Path(a.arquivo)
    try:
        if a.cmd == "novo":
            if path.exists():
                print(f"{path} já existe; nada feito.")
                return 1
            save_spec(blank_spec(a.titulo), path)
            print(f"Criado {path}. Edite com:  python main.py editar {path}")
        elif a.cmd == "gerar":
            spec = load_spec(path)
            for out in a.saida or [str(path.with_suffix(".pdf"))]:
                render(spec, Path(out), a.tema, a.pagina)
                print(f"gerado: {out}")
        elif a.cmd == "listar":
            Editor(path, load_spec(path)).do_listar("")
        elif a.cmd in ("gui", "interface"):
            try:
                from gui import launch_gui
            except ModuleNotFoundError as ex:
                if ex.name and ex.name.startswith("PySide6"):
                    print("A interface gráfica precisa do PySide6. Instale com: py -m pip install PySide6",
                          file=sys.stderr)
                    return 1
                raise
            return launch_gui(path, load_spec=load_spec, save_spec=save_spec,
                              blank_spec=blank_spec, validate=validate,
                              build=build, render=render,
                              example_path=Path(__file__).with_name("fluxo.json"))
        elif a.cmd == "editar":
            if path.exists():
                spec = load_spec(path)
            else:
                print(f"{path} não existe; começando um fluxo novo (use 'salvar').")
                spec = blank_spec()
            ed = Editor(path, spec, auto=a.auto)
            if a.auto:
                ed._render(ed.last_out, quiet=True)
            ed.cmdloop()
    except (OSError, ValueError, KeyError) as ex:
        print(f"Erro: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # Windows consoles started with a legacy code page may not be able to
    # print arrows and other UTF-8 characters used by the CLI.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure and not (getattr(stream, "encoding", "") or "").lower().replace("-", "") == "utf8":
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    sys.exit(main())
