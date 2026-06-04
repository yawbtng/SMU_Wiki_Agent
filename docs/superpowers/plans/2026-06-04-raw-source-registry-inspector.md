# Raw Source Registry Inspector

## Goal

Make the Sources tab raw source registry useful by letting an operator click a row and inspect the underlying raw markdown/source content, with enough metadata to understand what the source is without opening files manually.

## Scope

Edit only:

- `frontend/src/main.tsx`
- `frontend/src/styles.css`

Preserve existing dirty work in these files, especially:

- Workspace dashboard and return/X navigation.
- Available areas dynamic selection and grouped area UI.
- Existing document preview behavior in the Documents tab.

## Expected Behavior

1. Raw source registry rows are clickable.
2. Clicking a row selects it and opens an adjacent or below-table source inspector.
3. The inspector shows useful metadata:
   - title
   - kind
   - status
   - wiki status
   - source ID
   - original URL when present
   - markdown path when present
4. If `markdown_path` is present, fetch the existing endpoint:

   ```text
   /api/sites/{siteId}/document-preview?path={markdown_path}
   ```

   and render it with the existing `MarkdownPreview` component.
5. If no markdown path exists, show a clear empty state with the source URL/path that can be inspected externally.
6. Keep the table compact, but make the most useful columns visible first. Avoid presenting the ID/path as the primary thing the user sees.

## Implementation Notes

- Use existing `DataTable` `onRowClick` support.
- Add local state in `Sources` for the selected raw source row.
- Add a React Query preview query keyed by selected source path.
- Avoid new dependencies.
- Keep CSS aligned with the existing operator UI.

## Verification

Run:

```bash
cd frontend && npx tsc --noEmit && npm run build
bash scripts/verify-webapp.sh
```

Runtime smoke:

```bash
curl -fsS 'http://127.0.0.1:8000/api/sites/www.smu.edu/sources?limit=1'
```

Use the returned `markdown_path`, if present, to confirm:

```bash
curl -fsS 'http://127.0.0.1:8000/api/sites/www.smu.edu/document-preview?path=<encoded-markdown-path>'
```

After edits:

```bash
codegraph sync && codegraph status
```
