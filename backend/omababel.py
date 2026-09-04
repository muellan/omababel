#!/usr/bin/env python3
"""omababel backend – JSON protocol for the Quickshell panel + a small CLI.

Protocol (used by the QML panel)::

    $ echo '{"op": "search", "params": {"mode": "lookup", "query": "Haus", "lang": "de"}}' \\
        | python3 backend/omababel.py
    {"ok": true, "data": {...}}

Long running operations (``data.install``) stream progress objects, one JSON
object per line, before the final ``{"ok": ...}`` line.

CLI (for humans and scripts)::

    omababel lookup Haus --lang de
    omababel thesaurus house --lang en
    omababel translate "guten Morgen" --from de --to en
    omababel data list | install wiktionary-de | remove ... | import <id> <file>
    omababel sources list | enable <id> | disable <id> | reset
    omababel history list | clear

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Callable, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ob import __version__, clipboard, data, impersonate, languages, paths, render, search, secrets  # noqa: E402
from ob import sources as S  # noqa: E402
from ob.config import Prefs, SourcesConfig  # noqa: E402
from ob.history import History  # noqa: E402


class RequestError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ------------------------------------------------------------------ operations

def op_state(params: dict) -> dict:
    cfg = SourcesConfig()
    prefs = Prefs()
    hist = History()
    return {
        "version": __version__,
        "sources": cfg.public(),
        "drivers": S.registry(),
        "languages": languages.options(),
        "prefs": prefs.data,
        "history": hist.list(),
        "history_max": hist.limit,
        "coverage": search.coverage(cfg),
        "keyring": {"available": secrets.available(), "backend": secrets.backend_name()},
        "paths": {"config": str(paths.config_dir()), "data": str(paths.data_dir()),
                  "state": str(paths.state_dir()), "cache": str(paths.cache_dir())},
    }


def op_search(params: dict) -> dict:
    mode = params.get("mode") or "lookup"
    query = str(params.get("query") or "").strip()
    lang = languages.normalize(params.get("lang")) or "en"
    lang2 = languages.normalize(params.get("lang2")) or ""
    if not query:
        raise RequestError("empty_query", "Nothing to search for.")
    if mode == "translate" and not lang2:
        raise RequestError("missing_language", "Choose a target language.")
    only = params.get("only") or None
    result = search.run(mode, query, lang, lang2, only=only)
    if params.get("html", True):
        render.decorate(result)
    if not params.get("no_history"):
        History().add(query, mode=mode, lang=lang, lang2=lang2)
    return result


def op_history_list(params: dict) -> dict:
    hist = History()
    limit = int(params["limit"]) if params.get("limit") else None
    return {"history": hist.list(prefix=str(params.get("prefix") or ""), limit=limit),
            "history_max": hist.limit}


def op_history_remove(params: dict) -> dict:
    return {"removed": History().remove(str(params.get("query") or ""))}


def op_history_clear(params: dict) -> dict:
    History().clear()
    return {"cleared": True}


def op_prefs_set(params: dict) -> dict:
    values = params.get("values") if isinstance(params.get("values"), dict) else params
    prefs = Prefs().update(values)
    out = {"prefs": prefs}
    if "history_max" in values:
        # apply the new cap right away and report the trimmed list
        hist = History()
        out["history"] = hist.list()
        out["history_max"] = hist.limit
    return out


def op_sources_list(params: dict) -> dict:
    return {"sources": SourcesConfig().public()}


def op_sources_save(params: dict) -> dict:
    src = params.get("source")
    if not isinstance(src, dict):
        raise RequestError("bad_request", "source object required")
    cfg = SourcesConfig()
    if src.get("driver") and src["driver"] not in S.all_drivers():
        raise RequestError("bad_driver", f"unknown driver '{src['driver']}'")
    # The secret never travels with the row: an empty api_key from the UI
    # means "keep the stored one" unless clear_key is set, and a new one goes
    # straight into the keyring (see ob.secrets).
    key = str(src.get("api_key") or "")
    existing = cfg.get(str(src.get("id") or ""))
    src = dict(src)
    if existing is not None and not key and not params.get("clear_key"):
        src["has_key"] = existing.get("has_key", False)   # keep the stored one
    try:
        row = cfg.upsert(src)
        if params.get("clear_key") and not key:
            cfg.set_key(row["id"], "")
    except secrets.SecretError as e:
        raise RequestError("keyring", f"Cannot store the key in the keyring: {e}")
    public = dict(row)
    public["api_key"] = ""
    public["key_storage"] = secrets.describe(row)
    public["has_key"] = bool(public["key_storage"])
    return {"source": public, "sources": cfg.public()}


def op_sources_delete(params: dict) -> dict:
    cfg = SourcesConfig()
    ok = cfg.delete(str(params.get("id") or ""))
    return {"deleted": ok, "sources": cfg.public()}


def op_sources_enable(params: dict) -> dict:
    cfg = SourcesConfig()
    ok = cfg.set_enabled(str(params.get("id") or ""), bool(params.get("enabled", True)))
    return {"updated": ok, "sources": cfg.public()}


def op_sources_move(params: dict) -> dict:
    cfg = SourcesConfig()
    ids = params.get("ids") or [params.get("id") or ""]
    ok = cfg.move([str(x) for x in ids if x], int(params.get("delta") or 0))
    return {"moved": ok, "sources": cfg.public()}


def op_sources_reorder(params: dict) -> dict:
    """Drag and drop: put `ids` in front of `before` (or at the end)."""
    cfg = SourcesConfig()
    ids = [str(x) for x in (params.get("ids") or []) if x]
    ok = cfg.reorder(ids, str(params.get("before") or ""))
    return {"moved": ok, "sources": cfg.public()}


def op_sources_reset(params: dict) -> dict:
    cfg = SourcesConfig()
    cfg.reset_defaults()
    return {"sources": cfg.public()}


def op_sources_status(params: dict) -> dict:
    """Installed/not-installed info for local rows."""
    cfg = SourcesConfig()
    out = {}
    for row in cfg.sources:
        if row.get("driver") == "local":
            try:
                src = S.build(row)
                out[row["id"]] = src.status()  # type: ignore[attr-defined]
            except S.SourceError as e:
                out[row["id"]] = {"installed": False, "error": str(e)}
    return {"status": out, "coverage": search.coverage(cfg)}


def op_sources_test(params: dict) -> dict:
    cfg = SourcesConfig()
    row = cfg.get(str(params.get("id") or ""))
    if row is None:
        raise RequestError("not_found", "unknown source")
    row = dict(row)
    row["api_key"] = cfg.key_for(row["id"])
    src = S.build(row)
    mode = {"dictionary": "lookup", "thesaurus": "thesaurus", "translator": "translate"}[src.type]
    lang = languages.normalize(params.get("lang")) or (src.effective_languages() or ["en"])[0]
    lang2 = languages.normalize(params.get("lang2")) or ""
    if mode == "translate" and not lang2:
        pairs = src.effective_pairs()
        lang, lang2 = pairs[0] if pairs else (lang, "en" if lang != "en" else "de")
    query = str(params.get("query") or {"de": "Haus", "en": "house", "fr": "maison", "es": "casa",
                                         "pt": "casa", "zh": "家", "ja": "家"}.get(lang, "house"))
    # A test must work on a source that is switched off – that is the normal
    # state of a row somebody is still setting up.
    result = search.run(mode, query, lang, lang2, cfg=cfg, only=[src.id], include_disabled=True)
    return result


def op_data_list(params: dict) -> dict:
    return {"datasets": data.list_status()}


def op_data_install(params: dict) -> dict:
    ds = str(params.get("id") or "")
    if not ds:
        raise RequestError("bad_request", "dataset id required")

    def progress(evt: dict) -> None:
        _emit({"event": "progress", "id": ds, **evt})

    path = params.get("path")
    if path:
        return {"dataset": data.import_file(ds, Path(str(path)).expanduser(), progress=progress)}
    return {"dataset": data.install(ds, progress=progress, keep_download=bool(params.get("keep")))}


def op_data_remove(params: dict) -> dict:
    ds = str(params.get("id") or "")
    return {"removed": data.remove(ds), "dataset": data.status(ds)}


def op_copy(params: dict) -> dict:
    text = str(params.get("text") or "")
    if not text:
        raise RequestError("empty", "nothing to copy")
    return {"tool": clipboard.copy(text)}


def op_drivers(params: dict) -> dict:
    return {"drivers": S.registry()}


def op_ping(params: dict) -> dict:
    return {"pong": True, "version": __version__}


OPS: Dict[str, Callable[[dict], dict]] = {
    "ping": op_ping,
    "state.get": op_state,
    "search": op_search,
    "history.list": op_history_list,
    "history.remove": op_history_remove,
    "history.clear": op_history_clear,
    "prefs.set": op_prefs_set,
    "sources.list": op_sources_list,
    "sources.save": op_sources_save,
    "sources.delete": op_sources_delete,
    "sources.enable": op_sources_enable,
    "sources.move": op_sources_move,
    "sources.reorder": op_sources_reorder,
    "sources.reset": op_sources_reset,
    "sources.status": op_sources_status,
    "sources.test": op_sources_test,
    "data.list": op_data_list,
    "data.install": op_data_install,
    "data.remove": op_data_remove,
    "drivers.list": op_drivers,
    "copy": op_copy,
}


def handle(request: dict) -> dict:
    op = str(request.get("op") or "")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    fn = OPS.get(op)
    if fn is None:
        return {"ok": False, "error": {"code": "unknown_op", "message": f"unknown op '{op}'"}}
    try:
        paths.ensure_dirs()
        return {"ok": True, "op": op, "data": fn(params)}
    except RequestError as e:
        return {"ok": False, "op": op, "error": {"code": e.code, "message": str(e)}}
    except clipboard.ClipboardError as e:
        return {"ok": False, "op": op, "error": {"code": "clipboard", "message": str(e)}}
    except Exception as e:  # noqa: BLE001
        if os.environ.get("OMABABEL_DEBUG"):
            traceback.print_exc()
        return {"ok": False, "op": op, "error": {"code": "internal", "message": f"{type(e).__name__}: {e}"}}


def serve_stdin() -> int:
    # One request per process: a single JSON line (the panel never closes
    # stdin, so do not wait for EOF).
    raw = sys.stdin.readline()
    try:
        request = json.loads(raw) if raw.strip() else {}
    except ValueError as e:
        _emit({"ok": False, "error": {"code": "bad_json", "message": str(e)}})
        return 1
    if not isinstance(request, dict):
        _emit({"ok": False, "error": {"code": "bad_request", "message": "request must be a JSON object"}})
        return 1
    _emit(handle(request))
    return 0


# ------------------------------------------------------------------------ CLI

def _print_lookup(result: dict) -> None:
    for r in result["results"]:
        print(f"== {r['source']['name']}" + ("" if r["ok"] else f"  [error: {r['error']}]"))
        for e in r.get("entries", []):
            head = e["headword"]
            if e.get("pos"):
                head += f"  ({e['pos']})"
            if e.get("pronunciation"):
                head += f"  [{e['pronunciation']}]"
            print("  " + head)
            for s in e.get("senses", []):
                label = (s.get("label") + " ") if s.get("label") else "- "
                tags = f" [{', '.join(s['tags'])}]" if s.get("tags") else ""
                print(f"    {label}{s['gloss']}{tags}")
                for ex in s.get("examples", []):
                    print(f"        » {ex}")
                if s.get("synonyms"):
                    print(f"        syn: {', '.join(s['synonyms'])}")
            for k, v in e.get("extra", {}).items():
                print(f"    {k}: {v}")
        print()
    if result.get("skipped"):
        print("skipped: " + ", ".join(f"{s['name']} ({s['reason']})" for s in result["skipped"]))


def _print_thesaurus(result: dict) -> None:
    c = result.get("consolidated", {})
    print("Synonyms: " + (", ".join(c.get("synonyms", [])) or "–"))
    print("Antonyms: " + (", ".join(c.get("antonyms", [])) or "–"))
    for r in result["results"]:
        if not r["ok"]:
            print(f"  [{r['source']['name']}: {r['error']}]")


def _print_translation(result: dict) -> None:
    for r in result["results"]:
        print(f"== {r['source']['name']}" + ("" if r["ok"] else f"  [error: {r['error']}]"))
        if r.get("text"):
            print("  " + r["text"])
        for a in r.get("alternatives", []):
            print("  ~ " + a)
        for p in r.get("pairs", []):
            pos = f" ({p['pos']})" if p.get("pos") else ""
            note = f"  – {p['note']}" if p.get("note") else ""
            print(f"  {p['src']}  →  {p['dst']}{pos}{note}")
        print()


def cli(argv) -> int:
    ap = argparse.ArgumentParser(prog="omababel", description="omababel dictionary/thesaurus/translation backend")
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print raw JSON")
    sub = ap.add_subparsers(dest="cmd")

    _add_parser = sub.add_parser

    def add_parser(name, **kw):
        return _add_parser(name, parents=[common], **kw)

    sub.add_parser = add_parser

    p = sub.add_parser("lookup", help="dictionary lookup")
    p.add_argument("query", nargs="+")
    p.add_argument("--lang", default=None)
    p.add_argument("--only", action="append", help="restrict to source id (repeatable)")

    p = sub.add_parser("thesaurus", help="synonyms / antonyms")
    p.add_argument("query", nargs="+")
    p.add_argument("--lang", default=None)
    p.add_argument("--only", action="append")

    p = sub.add_parser("translate", help="translate a word or text")
    p.add_argument("query", nargs="+")
    p.add_argument("--from", dest="src", default=None)
    p.add_argument("--to", dest="dst", default=None)
    p.add_argument("--only", action="append")

    p = sub.add_parser("data", help="manage downloadable datasets")
    p.add_argument("action", choices=["list", "install", "remove", "status", "import"])
    p.add_argument("ids", nargs="*")
    p.add_argument("--keep", action="store_true", help="keep the downloaded file")

    p = sub.add_parser("sources", help="manage search sources")
    p.add_argument("action", choices=["list", "enable", "disable", "delete", "reset", "test", "path",
                                      "key", "forget-key", "keyring", "unblock"])
    p.add_argument("ids", nargs="*")

    p = sub.add_parser("history", help="search history")
    p.add_argument("action", choices=["list", "clear", "remove"])
    p.add_argument("query", nargs="*")

    sub.add_parser("state", help="dump the full UI state")
    sub.add_parser("drivers", help="list source drivers")
    sub.add_parser("serve", help="read one JSON request from stdin (what the panel does)")
    p = sub.add_parser("copy", help="copy text to the clipboard")
    p.add_argument("text", nargs="+")

    args = ap.parse_args(argv)
    if not args.cmd or args.cmd == "serve":
        return serve_stdin()

    prefs = Prefs().data

    def out(resp: dict, printer=None) -> int:
        if args.json or printer is None:
            print(json.dumps(resp, ensure_ascii=False, indent=2))
        elif resp.get("ok"):
            printer(resp["data"])
        else:
            print("error: " + resp["error"]["message"], file=sys.stderr)
        return 0 if resp.get("ok") else 1

    if args.cmd in ("lookup", "thesaurus"):
        mode = args.cmd
        resp = handle({"op": "search", "params": {"mode": mode, "query": " ".join(args.query),
                                                  "lang": args.lang or prefs.get("lang", "en"),
                                                  "only": args.only}})
        return out(resp, _print_lookup if mode == "lookup" else _print_thesaurus)
    if args.cmd == "translate":
        resp = handle({"op": "search", "params": {"mode": "translate", "query": " ".join(args.query),
                                                  "lang": args.src or prefs.get("lang", "de"),
                                                  "lang2": args.dst or prefs.get("lang2", "en"),
                                                  "only": args.only}})
        return out(resp, _print_translation)
    if args.cmd == "data":
        if args.action in ("list", "status"):
            resp = handle({"op": "data.list", "params": {}})

            def pr(d):
                for ds in d["datasets"]:
                    mark = "✔" if ds["installed"] else " "
                    extra = f"  {ds.get('entries', 0)} entries" if ds["installed"] else ""
                    print(f"[{mark}] {ds['id']:<28} {ds['title']}{extra}")
            return out(resp, pr)
        if args.action == "install":
            rc = 0
            for ds in args.ids:
                resp = handle({"op": "data.install", "params": {"id": ds, "keep": args.keep}})
                rc |= out(resp, lambda d: print(f"installed {d['dataset']['id']}: {d['dataset'].get('entries', 0)} entries"))
            return rc
        if args.action == "import":
            if len(args.ids) != 2:
                print("usage: omababel data import <dataset-id> <file>", file=sys.stderr)
                return 2
            resp = handle({"op": "data.install", "params": {"id": args.ids[0], "path": args.ids[1]}})
            return out(resp, lambda d: print(f"imported {d['dataset']['id']}: {d['dataset'].get('entries', 0)} entries"))
        if args.action == "remove":
            rc = 0
            for ds in args.ids:
                rc |= out(handle({"op": "data.remove", "params": {"id": ds}}),
                          lambda d: print("removed" if d["removed"] else "not installed"))
            return rc
    if args.cmd == "sources":
        if args.action == "list":
            def pr(d):
                for s in d["sources"]:
                    mark = "✔" if s["enabled"] else " "
                    loc = s["path"] if s["kind"] == "local" else s["url"]
                    key = f"  [key: {s['key_storage']}]" if s.get("key_storage") else ""
                    print(f"[{mark}] {s['id']:<34} {s['type']:<10} {s['driver']:<12} {loc}{key}")
            return out(handle({"op": "sources.list", "params": {}}), pr)
        if args.action in ("enable", "disable"):
            rc = 0
            for sid in args.ids:
                resp = handle({"op": "sources.enable", "params": {"id": sid, "enabled": args.action == "enable"}})
                rc |= out(resp, lambda d: print("ok" if d["updated"] else "unknown source"))
                if resp.get("ok") and not resp["data"]["updated"]:
                    rc = 1
            return rc
        if args.action == "delete":
            rc = 0
            for sid in args.ids:
                resp = handle({"op": "sources.delete", "params": {"id": sid}})
                rc |= out(resp, lambda d: print("deleted" if d["deleted"] else "unknown source"))
                if resp.get("ok") and not resp["data"]["deleted"]:
                    rc = 1
            return rc
        if args.action == "reset":
            return out(handle({"op": "sources.reset", "params": {}}), lambda d: print("sources reset to defaults"))
        if args.action == "test":
            rc = 0
            for sid in args.ids:
                resp = handle({"op": "sources.test", "params": {"id": sid}})
                if resp.get("ok"):
                    mode = resp["data"]["mode"]
                    printer = {"lookup": _print_lookup, "thesaurus": _print_thesaurus, "translate": _print_translation}[mode]
                    rc |= out(resp, printer)
                else:
                    rc |= out(resp)
            return rc
        if args.action == "path":
            print(str(paths.config_dir() / "sources.json"))
            return 0
        if args.action == "unblock":
            # Forget the cookies and the per-host pause the browser transport
            # keeps – the way out when a site has refused us and the backoff
            # is longer than one's patience.
            st = impersonate.state()
            hosts = args.ids or list(st.data.get("hosts", {}))
            for host in hosts:
                st.data.get("hosts", {}).pop(host, None)
                st.data.get("cookies", {}).pop(host, None)
            st.dirty = True
            st.save()
            print("cleared: " + (", ".join(hosts) if hosts else "nothing was blocked"))
            return 0
        if args.action == "keyring":
            if secrets.available():
                print(f"keyring: {secrets.backend_name()}")
                return 0
            print("no keyring available – install libsecret (secret-tool) and run a Secret Service\n"
                  "such as gnome-keyring, or point a source at an environment variable or a command.")
            return 1
        if args.action in ("key", "forget-key"):
            # The secret is read from stdin so it never shows up in the shell
            # history or in the process list, and never touches a file.
            rc = 0
            for sid in args.ids:
                cfg = SourcesConfig()
                if cfg.get(sid) is None:
                    print(f"unknown source '{sid}'", file=sys.stderr)
                    rc = 1
                    continue
                value = ""
                if args.action == "key":
                    if sys.stdin.isatty():
                        print(f"key for {sid} (input is not echoed to a file, end with Enter):", file=sys.stderr)
                    value = sys.stdin.readline().strip()
                    if not value:
                        print("empty key – nothing stored", file=sys.stderr)
                        rc = 1
                        continue
                try:
                    cfg.set_key(sid, value)
                except secrets.SecretError as e:
                    print(f"cannot store the key: {e}", file=sys.stderr)
                    rc = 1
                    continue
                print(f"{sid}: key {'stored in the keyring' if value else 'removed'}")
            return rc
    if args.cmd == "history":
        if args.action == "list":
            return out(handle({"op": "history.list", "params": {}}),
                       lambda d: [print(e["query"]) for e in d["history"]])
        if args.action == "clear":
            return out(handle({"op": "history.clear", "params": {}}), lambda d: print("history cleared"))
        if args.action == "remove":
            return out(handle({"op": "history.remove", "params": {"query": " ".join(args.query)}}),
                       lambda d: print("removed" if d["removed"] else "not found"))
    if args.cmd == "state":
        return out(handle({"op": "state.get", "params": {}}))
    if args.cmd == "drivers":
        return out(handle({"op": "drivers.list", "params": {}}),
                   lambda d: [print(f"{x['driver']:<14} {x['label']:<28} {', '.join(x['types'])}") for x in d["drivers"]])
    if args.cmd == "copy":
        return out(handle({"op": "copy", "params": {"text": " ".join(args.text)}}), lambda d: print(f"copied via {d['tool']}"))
    ap.print_help()
    return 2


def main() -> None:
    try:
        rc = cli(sys.argv[1:])
    except KeyboardInterrupt:
        rc = 130
    except BrokenPipeError:
        rc = 0
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (BrokenPipeError, OSError):
        pass
    # Do not wait for hung network threads.
    os._exit(rc)


if __name__ == "__main__":
    main()
