/** Fill the module-level call edges Graphify currently omits for JS/TS.
 * Graphify owns function-body calls; this only examines top-level expressions. */
import { existsSync, readFileSync } from "node:fs";
import { basename, resolve, sep } from "node:path";
import ts from "typescript";

export interface GraphNode {
  id: string;
  label?: string;
  source_file?: string;
  [key: string]: unknown;
}

export interface GraphLink {
  source: string;
  target: string;
  relation?: string;
  source_file?: string;
  source_location?: string;
  [key: string]: unknown;
}

const SCRIPT_KINDS: Record<string, ts.ScriptKind> = {
  ".js": ts.ScriptKind.JS,
  ".jsx": ts.ScriptKind.JSX,
  ".ts": ts.ScriptKind.TS,
  ".tsx": ts.ScriptKind.TSX,
  ".mjs": ts.ScriptKind.JS,
  ".cjs": ts.ScriptKind.JS,
  ".mts": ts.ScriptKind.TS,
  ".cts": ts.ScriptKind.TS,
};

function scriptKind(file: string): ts.ScriptKind | undefined {
  const extension = file.slice(file.lastIndexOf(".")).toLowerCase();
  return SCRIPT_KINDS[extension];
}

export function supplementTopLevelCalls(
  repoRoot: string,
  nodes: GraphNode[],
  graphEdges: GraphLink[],
): GraphLink[] {
  const byFile = new Map<string, GraphNode[]>();
  for (const node of nodes) {
    const file = node.source_file;
    if (!file || scriptKind(file) === undefined) continue;
    const group = byFile.get(file) ?? [];
    group.push(node);
    byFile.set(file, group);
  }

  const added: GraphLink[] = [];
  const seen = new Set(
    graphEdges
      .filter(
        (edge) =>
          edge.relation === "calls" || edge.relation === "indirect_call",
      )
      .map(
        (edge) =>
          `${edge.source_file}\0${edge.source_location}\0${edge.target}`,
      ),
  );
  const root = resolve(repoRoot);

  for (const [file, fileNodes] of byFile) {
    const fullPath = resolve(root, file);
    if (!fullPath.startsWith(root + sep) || !existsSync(fullPath)) continue;
    const source = ts.createSourceFile(
      file,
      readFileSync(fullPath, "utf8"),
      ts.ScriptTarget.Latest,
      false,
      scriptKind(file),
    );
    const symbols = new Map(fileNodes.map((node) => [node.label, node.id]));
    const fileNode = fileNodes.find((node) => node.label === basename(file));
    const declaredFunctions = new Map<string, string>();

    for (const statement of source.statements) {
      if (ts.isFunctionDeclaration(statement) && statement.name) {
        const id = symbols.get(`${statement.name.text}()`);
        if (id) declaredFunctions.set(statement.name.text, id);
      }
      if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          if (!ts.isIdentifier(declaration.name)) continue;
          if (
            declaration.initializer &&
            (ts.isArrowFunction(declaration.initializer) ||
              ts.isFunctionExpression(declaration.initializer))
          ) {
            const id = symbols.get(`${declaration.name.text}()`);
            if (id) declaredFunctions.set(declaration.name.text, id);
          }
        }
      }
    }

    const visit = (node: ts.Node, sourceId: string): void => {
      // Graphify already handles calls in function and class bodies.
      if (ts.isFunctionLike(node) || ts.isClassDeclaration(node)) return;
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
        const target = declaredFunctions.get(node.expression.text);
        if (target) {
          const line =
            source.getLineAndCharacterOfPosition(node.getStart(source)).line +
            1;
          const location = `L${line}`;
          const key = `${file}\0${location}\0${target}`;
          if (!seen.has(key)) {
            added.push({
              source: sourceId,
              target,
              relation: "calls",
              source_file: file,
              source_location: location,
              confidence: "EXTRACTED",
              _origin: "ast",
            });
            seen.add(key);
          }
        }
      }
      ts.forEachChild(node, (child) => visit(child, sourceId));
    };

    for (const statement of source.statements) {
      if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          if (!declaration.initializer) continue;
          const owner = ts.isIdentifier(declaration.name)
            ? (symbols.get(declaration.name.text) ?? fileNode?.id)
            : fileNode?.id;
          if (owner) visit(declaration.initializer, owner);
        }
      } else if (fileNode) {
        visit(statement, fileNode.id);
      }
    }
  }
  return added;
}
