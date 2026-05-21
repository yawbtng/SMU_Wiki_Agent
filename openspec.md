• /opsx here maps to the repo-local OpenSpec skills in .codex/skills. Available ones:

  /opsx:explore
  Use this when we are thinking, investigating, comparing options, or shaping requirements. It
  can read files and inspect the codebase, but it should not implement app code. Good for “let’s
  redesign PDF sources” or “is this architecture right?”

  /opsx:propose
  Use this when we are ready to turn an idea into OpenSpec artifacts. It creates a change under
  openspec/changes/<change-name>/ with proposal, design, specs, and tasks. This is what I used
  for build-llm-wiki-stepper.

  /opsx:apply
  Use this when you want implementation to start from an OpenSpec change. It reads the proposal/
  design/specs/tasks, works through tasks.md, edits code, and marks tasks complete as it goes.

  /opsx:archive
  Use this after implementation is complete. It checks artifact/task status, warns about
  incomplete work, optionally syncs delta specs into main specs, then moves the change into
  openspec/changes/archive/....

  Typical flow:

  /opsx:explore   → think through the idea
  /opsx:propose   → write the spec/change plan
  /opsx:apply     → implement the tasks
  /opsx:archive   → finalize after done

  Current active change we created:

  build-llm-wiki-stepper

  So implementation would be:

  /opsx:apply build-llm-wiki-stepper
