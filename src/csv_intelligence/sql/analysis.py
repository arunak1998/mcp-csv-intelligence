"""Facts read from a parsed query: its string filters, and whether it only returns aggregates."""

from sqlglot import exp

from csv_intelligence.sql.guard import TABLE


def _string_literal(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Literal) and node.is_string:
        return node.this
    return None


def string_filters(tree: exp.Expression) -> list[tuple[str, str]]:
    """(column, value) pairs from `column = 'x'`, `column <> 'x'` and `column IN ('x', ...)`.

    Only bare columns count: in `LOWER(region) = 'south'` the literal is already normalised,
    so replacing it with the stored spelling would break the query.
    """
    pairs = []
    for node in tree.find_all(exp.EQ, exp.NEQ):
        for column, other in ((node.left, node.right), (node.right, node.left)):
            value = _string_literal(other)
            if isinstance(column, exp.Column) and value is not None:
                pairs.append((column.name, value))
    for node in tree.find_all(exp.In):
        if isinstance(node.this, exp.Column):
            for item in node.expressions:
                value = _string_literal(item)
                if value is not None:
                    pairs.append((node.this.name, value))
    return pairs


def referenced_columns(tree: exp.Expression) -> set[str]:
    return {column.name for column in tree.find_all(exp.Column)}


def _reads_table_directly(select: exp.Select) -> bool:
    return any(
        table.name == TABLE and table.find_ancestor(exp.Select) is select
        for table in select.find_all(exp.Table)
    )


def _is_aggregate(projection: exp.Expression, select: exp.Select) -> bool:
    """An aggregate of this SELECT's rows; `SUM(x) OVER (...)` keeps one value per row, so it is not."""
    return any(
        function.find_ancestor(exp.Window) is None and function.find_ancestor(exp.Select) is select
        for function in projection.find_all(exp.AggFunc)
    )


def _select_is_aggregated(select: exp.Select) -> bool:
    if select.args.get("group"):
        return True
    return all(_is_aggregate(projection, select) for projection in select.expressions)


def returns_only_aggregates(tree: exp.Expression) -> bool:
    """True when every SELECT that reads the raw table groups or aggregates it.

    Selects over CTEs inherit this: if the CTE that scans `self` is aggregated,
    nothing built on top of it can bring raw rows back.
    """
    raw_scans = [select for select in tree.find_all(exp.Select) if _reads_table_directly(select)]
    return bool(raw_scans) and all(_select_is_aggregated(select) for select in raw_scans)


def group_by_columns(tree: exp.Expression) -> set[str]:
    names: set[str] = set()
    for group in tree.find_all(exp.Group):
        names.update(column.name for column in group.find_all(exp.Column))
    return names
