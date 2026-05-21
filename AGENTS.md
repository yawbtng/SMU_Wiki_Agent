## Verification Before Completion

- Before saying a fix is done, always run a compile/syntax check for changed code paths.
- If the change affects a running app/service, also run a runtime sanity check (logs or quick smoke path) and confirm no new exceptions.
- Report completion only after both checks pass, or clearly state what could not be verified.
