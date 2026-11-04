# 0008: Frontend stays plain ES modules with no build step

**Status:** Accepted (revisit if app.js keeps growing past ~3,000 lines)

**Context.** The UI (`frontend/`) is served as files by FastAPI and shown in a GTK WebKit window. TypeScript +
Vite would add Node, node_modules (hundreds of MB) and a build before every change.

**Decision.** Keep plain ES modules. Safety comes from: `make js-check` (every file must parse, also in CI),
`frontend/jsconfig.json` (VS Code IntelliSense across modules), and opt-in type checking per file with
`// @ts-check` at the top plus JSDoc types, which VS Code checks with no install.

**Consequences.** + Edit, reload, done; nothing to build or install. - Fewer compile-time checks than TypeScript.
The path up: add `// @ts-check` file by file, then move to TypeScript only when a second person works on the UI.
