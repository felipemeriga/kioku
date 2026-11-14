"""Small, fail-closed PostgreSQL metadata grammar; never execute model SQL verbatim."""

import re
from uuid import UUID

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

COLUMNS = frozenset(
    {
        "id",
        "user_id",
        "source_filename",
        "source_type",
        "content_hash",
        "status",
        "created_at",
        "last_updated",
        "root_folder_id",
        "folder_id",
        "metadata",
    }
)
# Node classes, rather than SQL keyword checks, deliberately exclude functions,
# operators and extensions not needed by the document metadata contract.
NODES = frozenset(
    {
        "Select",
        "From",
        "Table",
        "TableAlias",
        "Identifier",
        "Column",
        "Literal",
        "Alias",
        "Distinct",
        "Count",
        "Sum",
        "Min",
        "Max",
        "Avg",
        "Star",
        "Where",
        "And",
        "Or",
        "Not",
        "Paren",
        "EQ",
        "NEQ",
        "GT",
        "GTE",
        "LT",
        "LTE",
        "Is",
        "Null",
        "Boolean",
        "In",
        "Between",
        "Like",
        "ILike",
        "Escape",
        "Group",
        "Order",
        "Ordered",
        "Limit",
        "Offset",
        "Add",
        "Sub",
        "Mul",
        "Div",
        "Mod",
        "Neg",
        "Interval",
        "Var",
        "CurrentDate",
        "CurrentTimestamp",
        "TimestampTrunc",
        "DateTrunc",
        "Extract",
        "Cast",
        "DataType",
        "Coalesce",
        "Lower",
        "Upper",
        "Length",
        "JSONExtractScalar",
        "JSONExtract",
        "JSONPath",
        "JSONPathRoot",
        "JSONPathKey",
        "JSONPathSubscript",
        "Case",
        "If",
        "Having",
    }
)
UNITS = frozenset(
    {
        "YEAR",
        "YEARS",
        "QUARTER",
        "MONTH",
        "MONTHS",
        "WEEK",
        "WEEKS",
        "DAY",
        "DAYS",
        "HOUR",
        "HOURS",
        "MINUTE",
        "MINUTES",
        "SECOND",
        "SECONDS",
        "DOW",
        "DOY",
        "EPOCH",
    }
)
TYPES = frozenset(
    {
        "TEXT",
        "VARCHAR",
        "UUID",
        "DATE",
        "TIMESTAMP",
        "TIMESTAMPTZ",
        "INT",
        "BIGINT",
        "SMALLINT",
        "BOOLEAN",
        "FLOAT",
        "DOUBLE PRECISION",
        "DECIMAL",
        "JSON",
        "JSONB",
    }
)


def _parsed_metadata(sql: str) -> exp.Select:
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 8192:
        raise ValueError("Unsupported metadata query")
    try:
        statements = parse(sql, read="postgres", error_message_context=0)
    except (SqlglotError, ValueError, RecursionError):
        raise ValueError("Unsupported metadata query") from None
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError("Unsupported metadata query")
    tree = statements[0]
    nodes = list(tree.walk())
    if len(nodes) > 1000 or any(type(node).__name__ not in NODES for node in nodes):
        raise ValueError("Unsupported metadata query")
    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1 or len(list(tree.find_all(exp.Select))) != 1:
        raise ValueError("Unsupported metadata query")
    table = tables[0]
    if (
        table.name != "documents"
        or table.db not in ("", "public")
        or table.catalog
        or any(value for key, value in table.args.items() if key not in {"this", "db", "alias"})
    ):
        raise ValueError("Unsupported metadata query")
    alias = table.args.get("alias")
    if alias and (
        alias.args.get("columns") or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", alias.name)
    ):
        raise ValueError("Unsupported metadata query")
    from_ = tree.args.get("from_")
    if not from_ or from_.this is not table:
        raise ValueError("Unsupported metadata query")
    aliases = {item.alias for item in tree.expressions if item.alias}
    for node in nodes:
        if isinstance(node, exp.Column):
            alias_reference = (
                not node.table
                and node.name in aliases
                and node.find_ancestor(exp.Group, exp.Order) is not None
            )
            if (
                (node.name not in COLUMNS and not alias_reference)
                or node.table not in ("", table.alias_or_name)
                or node.db
                or node.catalog
            ):
                raise ValueError("Unsupported metadata query")
        if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
            raise ValueError("Unsupported metadata query")
        if isinstance(node, exp.Var) and node.name.upper() not in UNITS:
            raise ValueError("Unsupported metadata query")
        if isinstance(node, exp.DataType) and node.sql(dialect="postgres").upper() not in TYPES:
            raise ValueError("Unsupported metadata query")
    for key in ("limit", "offset"):
        value = tree.args.get(key)
        if value and (
            not isinstance(value.expression, exp.Literal)
            or value.expression.is_string
            or not value.expression.this.isdigit()
        ):
            raise ValueError("Unsupported metadata query")
    return tree


def scoped_metadata_sql(
    sql: str,
    user_id: str,
    root_folder_id: str | None = None,
    *,
    folder_ids: list[str] | None = None,
    filename: str | None = None,
) -> str:
    """Authorize at the outer WHERE; ORs/comments in model output cannot widen it."""
    owner = str(UUID(user_id))
    root = str(UUID(root_folder_id)) if root_folder_id is not None else None
    tree = _parsed_metadata(sql)
    table = next(tree.find_all(exp.Table))
    # The privileged RPC must not resolve an ambient pg_temp/search_path relation.
    table.set("db", exp.to_identifier("public"))
    predicates = [
        exp.EQ(
            this=exp.column("user_id", table=table.alias_or_name),
            expression=exp.Literal.string(owner),
        )
    ]
    if root:
        predicates.append(
            exp.EQ(
                this=exp.column("root_folder_id", table=table.alias_or_name),
                expression=exp.Literal.string(root),
            )
        )
    if folder_ids is not None:
        if len(folder_ids) > 10000:
            raise ValueError("Unsupported document scope")
        authorized = [str(UUID(folder)) for folder in folder_ids]
        predicates.append(
            exp.In(
                this=exp.column("folder_id", table=table.alias_or_name),
                expressions=[exp.Literal.string(folder) for folder in authorized],
            )
            if authorized
            else exp.Boolean(this=False)
        )
    if filename is not None:
        if not isinstance(filename, str) or not filename or len(filename) > 1000:
            raise ValueError("Unsupported document scope")
        predicates.append(
            exp.EQ(
                this=exp.column("source_filename", table=table.alias_or_name),
                expression=exp.Literal.string(filename),
            )
        )
    tree = tree.where(*predicates, append=True)
    limit = tree.args.get("limit")
    tree = tree.limit(min(int(limit.expression.this), 1000) if limit else 1000)
    # Preserve quoting/case of an existing alias in the server-owned predicates.
    alias = table.args.get("alias")
    identifier = alias.this if alias else table.this
    for column in tree.find_all(exp.Column):
        if column.table == table.alias_or_name:
            column.set("table", identifier.copy())
    return tree.sql(dialect="postgres", comments=False)
