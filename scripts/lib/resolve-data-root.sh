#!/usr/bin/env bash
# Resolve SCRAPE_PLANNER_DATA_ROOT across git worktrees.
# Mirrors src/scrape_planner/data_root.py.

resolve_data_root_has_sites() {
  local root="${1:-}"
  [[ -n "$root" ]] || return 1
  [[ -d "$root/sites" ]] || return 1
  local entry
  for entry in "$root/sites"/*; do
    [[ -e "$entry" ]] || continue
    [[ -d "$entry" || -L "$entry" ]] && return 0
  done
  return 1
}

resolve_data_root_has_artifacts() {
  local root="${1:-}"
  [[ -n "$root" ]] || return 1
  if resolve_data_root_has_sites "$root"; then
    return 0
  fi
  [[ -f "$root/app_state.json" && -s "$root/app_state.json" ]]
}

resolve_data_root_main_worktree() {
  local project_root="$1"
  local git_file="$project_root/.git"
  [[ -f "$git_file" ]] || return 0

  local content gitdir
  content="$(tr -d '[:space:]' <"$git_file")"
  [[ "$content" == gitdir:* ]] || return 0
  gitdir="${content#gitdir:}"
  [[ "$gitdir" != /* ]] && gitdir="$project_root/$gitdir"
  gitdir="$(cd "$(dirname "$gitdir")" && pwd)/$(basename "$gitdir")"

  if [[ "$(basename "$(dirname "$gitdir")")" == "worktrees" && "$(basename "$(dirname "$(dirname "$gitdir")")")" == ".git" ]]; then
    local main_root
    main_root="$(cd "$(dirname "$(dirname "$(dirname "$gitdir")")")" && pwd)"
    printf '%s\n' "$main_root"
  fi
}

resolve_data_root_sibling_candidates() {
  local project_root="$1"
  local parent sibling data_path
  parent="$(cd "$project_root/.." && pwd)"

  for sibling in "$parent"/*; do
    [[ -d "$sibling" ]] || continue
    [[ "$sibling" == "$project_root" ]] && continue
    data_path="$sibling/data"
    [[ -d "$data_path" ]] && printf '%s\n' "$data_path"
  done
}

resolve_data_root() {
  local project_root="${1:-}"
  [[ -n "$project_root" ]] || return 1
  project_root="$(cd "$project_root" && pwd)"

  local explicit="" key configured candidate
  for key in ULTRA_FAST_RAG_DATA_ROOT SCRAPE_PLANNER_DATA_ROOT; do
    configured="${!key:-}"
    configured="${configured#"${configured%%[![:space:]]*}"}"
    configured="${configured%"${configured##*[![:space:]]}"}"
    if [[ -n "$configured" ]]; then
      explicit="$(cd "$(dirname "$configured")" && pwd)/$(basename "$configured")"
      break
    fi
  done

  if [[ -n "$explicit" ]]; then
    if resolve_data_root_has_artifacts "$explicit" || [[ "${SCRAPE_PLANNER_DATA_ROOT_STRICT:-}" == "1" ]]; then
      printf '%s\n' "$explicit"
      return 0
    fi
    echo "[resolve-data-root] configured data root has no sites: $explicit (searching worktrees)" >&2
  fi

  local -a candidates=()
  candidates+=("$project_root/data")
  local main_root
  main_root="$(resolve_data_root_main_worktree "$project_root" || true)"
  if [[ -n "$main_root" && "$main_root" != "$project_root" ]]; then
    candidates+=("$main_root/data")
  fi
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] && candidates+=("$candidate")
  done < <(resolve_data_root_sibling_candidates "$project_root")

  for candidate in "${candidates[@]}"; do
    if resolve_data_root_has_artifacts "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if [[ -n "$explicit" ]]; then
    printf '%s\n' "$explicit"
    return 0
  fi
  printf '%s\n' "$project_root/data"
}

resolve_data_root_site_count() {
  local root count=0 entry
  root="$(resolve_data_root "${1:-}")" || return 1
  [[ -d "$root/sites" ]] || return 0
  for entry in "$root/sites"/*; do
    [[ -e "$entry" ]] || continue
    [[ -d "$entry" || -L "$entry" ]] && count=$((count + 1))
  done
  printf '%s\n' "$count"
}
