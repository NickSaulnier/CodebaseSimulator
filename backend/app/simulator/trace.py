from __future__ import annotations

from app.graph.store import GraphStore


def simulate_paths(
    store: GraphStore,
    entry_node_id: str,
    max_depth: int,
    max_paths: int = 200,
) -> tuple[list[list[str]], bool, int]:
    """
    Bounded DFS over CALLS edges. Skips edges that would revisit a node on the current chain.
    Returns (paths, truncated, cycles_skipped).
    """
    paths: list[list[str]] = []
    truncated = False
    cycles_skipped = 0

    if store.get_node(entry_node_id) is None:
        return [], False, 0

    def walk(cur: str, chain: list[str], stack_set: frozenset[str]) -> None:
        nonlocal truncated, cycles_skipped
        if len(paths) >= max_paths:
            truncated = True
            return
        edge_count = len(chain) - 1
        if edge_count >= max_depth:
            paths.append(chain)
            truncated = True
            return
        succ = store.call_successors(cur)
        if not succ:
            paths.append(chain)
            return
        for nxt in succ:
            if nxt in stack_set:
                cycles_skipped += 1
                continue
            walk(nxt, chain + [nxt], stack_set | {nxt})

    walk(entry_node_id, [entry_node_id], frozenset({entry_node_id}))
    if not paths:
        paths = [[entry_node_id]]
    return paths, truncated, cycles_skipped
