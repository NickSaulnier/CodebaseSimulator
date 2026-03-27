from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from tree_sitter import Node, Parser

from app.graph.store import GraphStore, ensure_module_node
from app.models import Confidence, EdgeKind, GraphNode, NodeKind, SourceSpan

try:
    from tree_sitter_languages import get_language
except ImportError as e:  # pragma: no cover
    raise ImportError("Install tree-sitter-languages: pip install tree-sitter-languages") from e

SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "build",
        ".next",
        "coverage",
        "__pycache__",
        ".venv",
        "venv",
    }
)

EXT_LANG = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}


def _txt(src: bytes, node: Node) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _span(node: Node) -> SourceSpan:
    sl, sc = node.start_point
    el, ec = node.end_point
    return SourceSpan(start_line=sl + 1, start_col=sc, end_line=el + 1, end_col=ec)


def _norm(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


def _symbol_id(file_norm: str, qual: str, line: int) -> str:
    return f"{file_norm}::{qual}@L{line}"


def discover_files(root: Path) -> list[Path]:
    out: list[Path] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext in EXT_LANG:
                out.append(Path(dirpath) / name)
    return sorted(out)


def _resolve_import_file(from_file: Path, spec: str) -> Path | None:
    """Resolve `from 'spec'` to an existing file path (JS/TS)."""
    if not spec or spec.startswith(("http:", "https:")):
        return None
    base = from_file.parent
    if spec.startswith("."):
        cand = (base / spec).resolve()
    else:
        # bare module — skip graph edge to file (no local file)
        return None
    exts_try = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]
    if cand.suffix.lower() in EXT_LANG:
        if cand.is_file():
            return cand
        # TypeScript often imports `./foo.js` while file is `foo.ts`
        if cand.suffix.lower() == ".js":
            stem = cand.with_suffix("")
            for ext in (".ts", ".tsx", ".js"):
                p = stem.with_suffix(ext)
                if p.is_file():
                    return p.resolve()
        return None
    for ext in exts_try:
        p = Path(str(cand) + ext) if ext else cand
        if p.is_file():
            return p.resolve()
        idx = p / "index"
        for e in (".ts", ".tsx", ".js", ".jsx"):
            ip = Path(str(idx) + e)
            if ip.is_file():
                return ip.resolve()
    return None


@dataclass
class ImportBinding:
    local: str
    remote: str | None  # export name in target, None means namespace/default unresolved


@dataclass
class FileContext:
    file_path: Path
    source: bytes
    module_id: str
    norm: str
    imports: list[tuple[str, Path | None, list[ImportBinding]]] = field(default_factory=list)
    # local name -> (resolved file path or None, remote export name or None for default)
    import_map: dict[str, tuple[Path | None, str | None]] = field(default_factory=dict)
    exports: dict[str, str] = field(default_factory=dict)  # export name -> symbol node id
    local_defs: dict[str, str] = field(default_factory=dict)  # qualname -> symbol id


def _parser_for(path: Path) -> Parser:
    ext = path.suffix.lower()
    lang_name = EXT_LANG.get(ext, "javascript")
    lang = get_language(lang_name)
    p = Parser()
    p.set_language(lang)
    return p


def _child_named(node: Node, name: str) -> Node | None:
    n = node.child_by_field_name(name)
    return n


def _call_callee(node: Node) -> Node | None:
    fn = node.child_by_field_name("function") or node.child_by_field_name("callee")
    if fn:
        return fn
    for ch in node.children:
        if ch.type == "arguments":
            break
        if ch.type not in ("(", ")", "?.", "optional_chain", "["):
            return ch
    return node.children[0] if node.children else None


def _find_defs_and_imports(ctx: FileContext, store: GraphStore, tree: Node) -> None:
    """First pass: imports, export map targets, function/class defs."""
    src = ctx.source
    norm = ctx.norm
    module_id = ctx.module_id

    def walk(node: Node, class_stack: list[str]) -> None:
        t = node.type
        if t == "import_statement":
            _parse_import(ctx, store, src, node)
            return
        if t == "export_statement":
            export_default = any(ch.type == "default" for ch in node.children)
            inner = node.child_by_field_name("declaration")
            if inner is None:
                for ch in node.children:
                    if ch.type == "export_clause":
                        _parse_export_clause(ctx, src, node, ch)
                    elif ch.type == "string":
                        # export * from 'x'
                        spec = _txt(src, ch).strip("'\"")
                        tgt = _resolve_import_file(ctx.file_path, spec)
                        if tgt:
                            _add_import_edges(ctx, store, module_id, tgt)
            elif inner is not None:
                if inner.type in ("function_declaration", "generator_function_declaration"):
                    _register_function(
                        ctx, store, src, inner, class_stack, exported=True, export_default=export_default
                    )
                elif inner.type == "class_declaration":
                    _register_class(ctx, store, src, inner, class_stack, exported=True, export_default=export_default)
                elif inner.type == "lexical_declaration":
                    for ch in inner.named_children:
                        if ch.type == "variable_declarator":
                            _maybe_register_var_function(
                                ctx, store, src, ch, class_stack, exported=True, export_default=export_default
                            )
            return
        if t == "function_declaration" or t == "generator_function_declaration":
            _register_function(ctx, store, src, node, class_stack, exported=False)
            return
        if t == "class_declaration":
            _register_class(ctx, store, src, node, class_stack, exported=False)
            return
        if t == "lexical_declaration" or t == "variable_declaration":
            for ch in node.named_children:
                if ch.type == "variable_declarator":
                    _maybe_register_var_function(ctx, store, src, ch, class_stack, exported=False)
            return
        if t == "method_definition" or t == "public_field_definition":
            # handled inside class body visit
            pass
        for ch in node.children:
            if t == "class_declaration" and ch.type == "class_body":
                name_n = _child_named(node, "name")
                cname = _txt(src, name_n) if name_n else "anonymous"
                walk(ch, class_stack + [cname])
            elif t == "class_body":
                walk(ch, class_stack)
            else:
                walk(ch, class_stack)

    walk(tree, [])

    # build import_map from parsed imports
    for _spec_str, resolved_path, bindings in ctx.imports:
        for b in bindings:
            ctx.import_map[b.local] = (resolved_path, b.remote)


def _parse_import(ctx: FileContext, store: GraphStore, src: bytes, node: Node) -> None:
    spec_node = node.child_by_field_name("source")
    if spec_node is None:
        return
    spec = _txt(src, spec_node).strip("'\"")
    resolved = _resolve_import_file(ctx.file_path, spec)
    bindings: list[ImportBinding] = []
    for ch in node.children:
        if ch.type != "import_clause":
            continue
        has_named = False
        for c2 in ch.children:
            if c2.type == "named_imports":
                has_named = True
                for c3 in c2.children:
                    if c3.type == "import_specifier":
                        loc = c3.child_by_field_name("name")
                        ali = c3.child_by_field_name("alias")
                        local_n = _txt(src, ali or loc)
                        rem = _txt(src, loc)
                        bindings.append(ImportBinding(local=local_n, remote=rem))
            elif c2.type == "identifier":
                bindings.append(ImportBinding(local=_txt(src, c2), remote="default"))
    if not bindings:
        if resolved:
            _add_import_edges(ctx, store, ctx.module_id, resolved)
        return
    ctx.imports.append((spec, resolved, bindings))
    if resolved:
        _add_import_edges(ctx, store, ctx.module_id, resolved)


def _add_import_edges(ctx: FileContext, store: GraphStore | None, module_id: str, tgt: Path) -> None:
    if store is None:
        return
    mid = ensure_module_node(store, _norm(tgt))
    store.add_edge(module_id, mid, EdgeKind.IMPORTS)


def _parse_export_clause(ctx: FileContext, src: bytes, export_node: Node, clause: Node) -> None:
    for ch in clause.children:
        if ch.type == "export_specifier":
            orig = ch.child_by_field_name("name")
            ali = ch.child_by_field_name("alias")
            name = _txt(src, ali or orig)
            if name in ctx.local_defs:
                ctx.exports[name] = ctx.local_defs[name]


def _register_class(
    ctx: FileContext,
    store: GraphStore,
    src: bytes,
    node: Node,
    class_stack: list[str],
    exported: bool,
    export_default: bool = False,
) -> None:
    name_n = _child_named(node, "name")
    cname = _txt(src, name_n) if name_n else "anonymous"
    line = node.start_point[0] + 1
    qual = f"{class_stack[-1]}.{cname}" if class_stack else cname
    sid = _symbol_id(ctx.norm, qual, line)
    span = _span(node)
    store.add_node(
        GraphNode(
            id=sid,
            kind=NodeKind.CLASS,
            name=cname,
            filePath=ctx.norm,
            span=span,
        )
    )
    store.add_edge(ctx.module_id, sid, EdgeKind.DEFINES)
    ctx.local_defs[qual] = sid
    if exported:
        ctx.exports[cname] = sid
        if export_default:
            ctx.exports["default"] = sid
    body = _child_named(node, "body")
    if body:
        for ch in body.children:
            if ch.type == "method_definition":
                _register_method(ctx, store, src, ch, qual, class_stack + [cname], exported=False)
            elif ch.type == "public_field_definition":
                fn = ch.child_by_field_name("name")
                val = ch.child_by_field_name("value")
                if fn and val and val.type in ("arrow_function", "function_expression", "generator_function"):
                    mname = _txt(src, fn)
                    line_m = ch.start_point[0] + 1
                    qual_m = f"{qual}.{mname}"
                    sid_m = _symbol_id(ctx.norm, qual_m, line_m)
                    store.add_node(
                        GraphNode(
                            id=sid_m,
                            kind=NodeKind.FUNCTION,
                            name=mname,
                            filePath=ctx.norm,
                            span=_span(ch),
                            isAsync=_has_async(val),
                        )
                    )
                    store.add_edge(sid, sid_m, EdgeKind.DEFINES)
                    ctx.local_defs[qual_m] = sid_m


def _has_async(fn_node: Node) -> bool:
    for c in fn_node.children:
        if c.type == "async":
            return True
    return False


def _register_method(
    ctx: FileContext,
    store: GraphStore,
    src: bytes,
    node: Node,
    class_qual: str,
    _stack: list[str],
    exported: bool,
) -> None:
    name_n = _child_named(node, "name")
    if name_n is None:
        return
    mname = _txt(src, name_n)
    line = node.start_point[0] + 1
    qual = f"{class_qual}.{mname}"
    sid = _symbol_id(ctx.norm, qual, line)
    store.add_node(
        GraphNode(
            id=sid,
            kind=NodeKind.FUNCTION,
            name=mname,
            filePath=ctx.norm,
            span=_span(node),
            isAsync=_has_async(node),
        )
    )
    cls_id = ctx.local_defs.get(class_qual)
    if cls_id:
        store.add_edge(cls_id, sid, EdgeKind.DEFINES)
    if exported:
        ctx.exports[mname] = sid


def _register_function(
    ctx: FileContext,
    store: GraphStore,
    src: bytes,
    node: Node,
    class_stack: list[str],
    exported: bool,
    export_default: bool = False,
) -> None:
    name_n = _child_named(node, "name")
    if name_n is None:
        return
    fname = _txt(src, name_n)
    line = node.start_point[0] + 1
    qual = f"{class_stack[-1]}.{fname}" if class_stack else fname
    sid = _symbol_id(ctx.norm, qual, line)
    store.add_node(
        GraphNode(
            id=sid,
            kind=NodeKind.FUNCTION,
            name=fname,
            filePath=ctx.norm,
            span=_span(node),
            isAsync=_has_async(node),
        )
    )
    store.add_edge(ctx.module_id, sid, EdgeKind.DEFINES)
    ctx.local_defs[qual] = sid
    if exported:
        ctx.exports[fname] = sid
        if export_default:
            ctx.exports["default"] = sid


def _maybe_register_var_function(
    ctx: FileContext,
    store: GraphStore,
    src: bytes,
    decl: Node,
    class_stack: list[str],
    exported: bool,
    export_default: bool = False,
) -> None:
    name_n = _child_named(decl, "name")
    val = _child_named(decl, "value")
    if name_n is None or val is None:
        return
    if val.type not in ("arrow_function", "function_expression", "generator_function"):
        return
    fname = _txt(src, name_n)
    line = decl.start_point[0] + 1
    qual = f"{class_stack[-1]}.{fname}" if class_stack else fname
    sid = _symbol_id(ctx.norm, qual, line)
    store.add_node(
        GraphNode(
            id=sid,
            kind=NodeKind.FUNCTION,
            name=fname,
            filePath=ctx.norm,
            span=_span(decl),
            isAsync=_has_async(val),
        )
    )
    store.add_edge(ctx.module_id, sid, EdgeKind.DEFINES)
    ctx.local_defs[qual] = sid
    if exported:
        ctx.exports[fname] = sid
        if export_default:
            ctx.exports["default"] = sid


def _unknown_node(store: GraphStore, label: str, line: int) -> str:
    uid = f"unknown::{label}@L{line}"
    if store.get_node(uid):
        return uid
    store.add_node(
        GraphNode(
            id=uid,
            kind=NodeKind.UNKNOWN,
            name=label,
            filePath="",
            confidence=Confidence.INFERRED,
        )
    )
    return uid


# Cross-file export registry filled before resolving calls
_GLOBAL_EXPORTS: dict[str, dict[str, str]] = {}


def _resolve_call_target_global(
    ctx: FileContext, name: str
) -> tuple[str | None, Confidence, str | None]:
    if name in ctx.local_defs:
        return ctx.local_defs[name], Confidence.CERTAIN, None
    for q, sid in ctx.local_defs.items():
        if q == name or q.endswith("." + name):
            return sid, Confidence.CERTAIN, None
    if name in ctx.import_map:
        path, remote = ctx.import_map[name]
        if path is None:
            return None, Confidence.INFERRED, name
        fnorm = _norm(path)
        exp = _GLOBAL_EXPORTS.get(fnorm, {})
        if remote == "default":
            if "default" in exp:
                return exp["default"], Confidence.CERTAIN, None
            return None, Confidence.INFERRED, name
        key = remote if remote is not None else name
        if key in exp:
            return exp[key], Confidence.CERTAIN, None
        return None, Confidence.INFERRED, name
    return None, Confidence.INFERRED, name


def _resolve_member_import(
    ctx: FileContext, obj: Node, prop: str, src: bytes
) -> tuple[str | None, Confidence, str | None]:
    oname = _txt(src, obj)
    if oname not in ctx.import_map:
        return None, Confidence.INFERRED, prop
    path, remote = ctx.import_map[oname]
    if path is None:
        return None, Confidence.INFERRED, prop
    fnorm = _norm(path)
    exp = _GLOBAL_EXPORTS.get(fnorm, {})
    if prop in exp:
        return exp[prop], Confidence.CERTAIN, prop
    return None, Confidence.INFERRED, prop


def _patch_record_call_global(ctx: FileContext, store: GraphStore, src: bytes, caller_id: str, callee: Node, line: int) -> None:
    if callee.type == "identifier":
        name = _txt(src, callee)
        tgt, conf, label = _resolve_call_target_global(ctx, name)
        if tgt:
            store.add_edge(caller_id, tgt, EdgeKind.CALLS, confidence=conf, label=label)
        else:
            unk = _unknown_node(store, name, line)
            store.add_edge(caller_id, unk, EdgeKind.CALLS, confidence=Confidence.INFERRED, label=label or name)
        return
    if callee.type == "member_expression":
        obj = _child_named(callee, "object")
        prop = _child_named(callee, "property")
        if obj and prop and prop.type in ("property_identifier", "identifier"):
            pname = _txt(src, prop)
            if obj.type == "identifier":
                tgt, conf, label = _resolve_member_import(ctx, obj, pname, src)
                if tgt:
                    store.add_edge(caller_id, tgt, EdgeKind.CALLS, confidence=conf, label=label)
                    return
            lbl = _txt(src, callee)
            unk = _unknown_node(store, lbl, line)
            store.add_edge(caller_id, unk, EdgeKind.CALLS, confidence=Confidence.INFERRED, label=lbl)
            return
    if callee.type == "parenthesized_expression":
        inner = callee.child_by_field_name("expression") or (
            callee.children[1] if len(callee.children) > 1 else None
        )
        if inner:
            _patch_record_call_global(ctx, store, src, caller_id, inner, line)
        return
    unk = _unknown_node(store, f"dynamic@{line}", line)
    store.add_edge(caller_id, unk, EdgeKind.CALLS, confidence=Confidence.INFERRED, label="dynamic")


def _second_pass_calls_global(ctx: FileContext, store: GraphStore, tree: Node) -> None:
    src = ctx.source

    def walk(node: Node, fn_stack: list[str]) -> None:
        t = node.type
        if t == "variable_declarator":
            name_n = _child_named(node, "name")
            val = _child_named(node, "value")
            if name_n and val and val.type in ("arrow_function", "function_expression", "generator_function"):
                nms = _txt(src, name_n)
                new_stack = fn_stack + [nms]
                walk(val, new_stack)
                return
            for ch in node.children:
                walk(ch, fn_stack)
            return
        if t in ("function_declaration", "generator_function_declaration"):
            name_n = _child_named(node, "name")
            qual = _txt(src, name_n) if name_n else None
            new_stack = fn_stack + ([qual] if qual else [])
            body = _child_named(node, "body")
            if body:
                walk(body, new_stack)
            return
        if t in ("arrow_function", "function_expression"):
            anon = f"anon@{node.start_point[0]}"
            new_stack = fn_stack + [anon]
            body = _child_named(node, "body")
            if body:
                walk(body, new_stack)
            return
        if t == "class_declaration":
            name_n = _child_named(node, "name")
            cname = _txt(src, name_n) if name_n else "anonymous"
            body = _child_named(node, "body")
            if body:
                for ch in body.children:
                    if ch.type == "method_definition":
                        mn = _child_named(ch, "name")
                        mname = _txt(src, mn) if mn else "?"
                        mq = f"{cname}.{mname}"
                        mb = _child_named(ch, "body")
                        if mb:
                            walk(mb, fn_stack + [mq])
                    else:
                        walk(ch, fn_stack + [cname])
            return
        if t == "call_expression":
            callee = _call_callee(node)
            caller_qual = fn_stack[-1] if fn_stack else None
            caller_id = ctx.local_defs.get(caller_qual) if caller_qual else None
            if caller_id and callee:
                _patch_record_call_global(ctx, store, src, caller_id, callee, node.start_point[0] + 1)
            for ch in node.children:
                walk(ch, fn_stack)
            return
        for ch in node.children:
            walk(ch, fn_stack)

    walk(tree, [])


def analyze_directory(root: Path) -> GraphStore:
    global _GLOBAL_EXPORTS
    _GLOBAL_EXPORTS = {}
    root = root.resolve()
    files = discover_files(root)
    store = GraphStore()
    contexts: list[FileContext] = []

    for fp in files:
        try:
            source = fp.read_bytes()
        except OSError:
            continue
        norm = _norm(fp)
        mod_id = ensure_module_node(store, norm)
        parser = _parser_for(fp)
        tree = parser.parse(source)
        ctx = FileContext(
            file_path=fp,
            source=source,
            module_id=mod_id,
            norm=norm,
        )
        _find_defs_and_imports(ctx, store, tree.root_node)
        _GLOBAL_EXPORTS[norm] = dict(ctx.exports)
        # merge re-exports: export { x } from './y'
        for ch in tree.root_node.children:
            if ch.type != "export_statement":
                continue
            src_n = ch.child_by_field_name("source")
            if src_n is None:
                continue
            spec = _txt(source, src_n).strip("'\"")
            tgt_path = _resolve_import_file(fp, spec)
            if not tgt_path:
                continue
            fn = _norm(tgt_path)
            exp = _GLOBAL_EXPORTS.get(fn, {})
            for sub in ch.children:
                if sub.type != "export_clause":
                    continue
                for spec_n in sub.children:
                    if spec_n.type != "export_specifier":
                        continue
                    orig = spec_n.child_by_field_name("name")
                    if orig is None:
                        continue
                    ename = _txt(source, orig)
                    if ename in exp and ename not in ctx.exports:
                        ctx.exports[ename] = exp[ename]
        _GLOBAL_EXPORTS[norm] = dict(ctx.exports)
        contexts.append(ctx)

    # Second pass: calls with global export map
    for ctx in contexts:
        parser = _parser_for(ctx.file_path)
        tree = parser.parse(ctx.source)
        _second_pass_calls_global(ctx, store, tree.root_node)

    return store
