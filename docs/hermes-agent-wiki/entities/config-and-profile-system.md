# Config and Profile System

## Overview

The config and profile system is Hermes's configuration layer, not just a pair of files.

Its job is to answer three questions before the rest of the runtime can behave correctly:

1. Which Hermes instance is active right now?
2. Which filesystem state belongs to that instance?
3. Which settings come from persisted config, which come from secrets, and which are only fallbacks?

That is why this page sits beside the shell pages instead of beneath them. The [CLI Runtime](cli-runtime.md), gateway, ACP, cron, and other entrypoints all depend on the same profile-scoped home directory. Once `HERMES_HOME` is fixed, Hermes can find the active `config.yaml`, `.env`, `SOUL.md`, memories, sessions, logs, and other per-instance state. If `HERMES_HOME` is wrong or is set too late, the rest of the process will read and cache the wrong files.

The short mental model is:

- `HERMES_HOME` is the root of one Hermes instance's persistent state
- profiles are named ways to switch that root, but a preexisting `HERMES_HOME` can also point Hermes at a custom root
- `config.yaml` stores structured non-secret settings
- `.env` stores secrets and env-shaped toggles
- `DEFAULT_CONFIG` fills in missing structure so callers do not need to handle partial files everywhere

## Key Types / Key Concepts

| Anchor | Role in the configuration layer |
| --- | --- |
| `get_hermes_home()` in `hermes_constants.py` | Canonical path resolver for the active Hermes home; every profile-aware subsystem depends on it. |
| `_apply_profile_override()` in `hermes_cli/main.py` | Pre-import profile selector that sets `HERMES_HOME` before most Hermes modules load. |
| `resolve_profile_env()` in `hermes_cli/profiles.py` | Turns a profile name into the exact `HERMES_HOME` path string used by startup. |
| `load_hermes_dotenv()` in `hermes_cli/env_loader.py` | Loads the active profile's `.env` first, then the repo `.env` as a development fallback. |
| `ensure_hermes_home()` in `hermes_cli/config.py` | Bootstraps the home-directory skeleton and seeds `SOUL.md`. |
| `DEFAULT_CONFIG` in `hermes_cli/config.py` | Built-in schema and defaults for structured settings. |
| `load_config()` / `save_config()` | Deep-merge persisted `config.yaml` with defaults, then normalize and persist structured settings. |
| `load_env()` / `get_env_value()` / `save_env_value()` | Read and persist secret or env-shaped values in the active profile's `.env`. |
| `active_profile` | Sticky default-profile file under `~/.hermes/active_profile`, used when no explicit `--profile` flag is passed. |
| managed install signals | `HERMES_MANAGED` or a `.managed` marker in `HERMES_HOME`, which switch Hermes into package-manager-owned behavior. |

## Architecture

The configuration layer is split on purpose. Different modules own different phases of the problem.

| Module | Owns | Stops before |
| --- | --- | --- |
| `hermes_constants.py` | the import-safe definition of `get_hermes_home()` and other profile-aware path helpers | profile selection, file loading, persistence |
| `hermes_cli/main.py` | very early profile activation, dotenv loading, and process startup ordering | structured config merge, setup UX, provider-specific policy |
| `hermes_cli/profiles.py` | named-profile lifecycle, wrapper scripts, sticky default profile, and profile-path resolution | normal config reads and writes inside a running profile |
| `hermes_cli/config.py` | home bootstrap, defaults, `config.yaml` merge/save, `.env` read/write, managed-install guards | interactive setup flow and runtime-specific interpretation of settings |
| `hermes_cli/setup.py` | guided user flows that write into `config.yaml` and `.env` through config helpers | being the source of truth itself |

That split creates a useful ownership boundary.

This page is about how Hermes decides where configuration lives and how it is read or persisted. It is **not** the place that explains how a provider is selected for one turn, how tools are enabled for a shell, or how prompt layers are assembled. Those subsystems consume the configuration layer after it has already resolved the active home and loaded the relevant files.

## What Lives Under `HERMES_HOME`

Once a profile is active, Hermes treats that directory as the persistent root for one agent instance.

`ensure_hermes_home()` creates or expects a profile-local layout centered on:

| Path under `HERMES_HOME` | What it stores | Why it matters |
| --- | --- | --- |
| `config.yaml` | structured settings such as model, terminal, memory, tools, display, approvals, fallback, and plugin-related config | this is the main persisted config surface |
| `.env` | API keys, tokens, passwords, and env-shaped runtime toggles | secrets live here instead of inside `config.yaml` |
| `SOUL.md` | the durable identity file for the agent | prompt assembly depends on it, but the config layer owns where it lives |
| `memories/` | persistent memory files | keeps memory scoped to the active profile |
| `sessions/` | session and gateway continuity data | lets multiple profiles stay isolated |
| `logs/` | profile-local logs | avoids cross-profile operational mixing |
| `cron/` | scheduled-job state | keeps automations tied to one Hermes instance |

Other files also live nearby when relevant, such as `auth.json` for OAuth-style provider state and `.managed` for package-manager ownership markers. Those files are part of the same filesystem root, but they are adjacent persistence artifacts rather than the primary config surfaces.

## Runtime Behavior

The easiest way to understand this subsystem is to follow startup in order.

### 1. Hermes chooses the active profile before normal imports

`hermes_cli/main.py` runs `_apply_profile_override()` before most Hermes modules are imported.

That function applies startup root selection in this order:

1. explicit `--profile` / `-p`
2. explicit `--profile=<name>`
3. non-default `~/.hermes/active_profile`
4. otherwise, leave any preexisting `HERMES_HOME` untouched
5. if no env var is set, `get_hermes_home()` falls back to `~/.hermes`

If a named profile is selected, `resolve_profile_env()` maps that name to `~/.hermes/profiles/<name>` and writes the result into `os.environ["HERMES_HOME"]`.

The important subtlety is step 4. `_apply_profile_override()` does not clear or replace an already-set `HERMES_HOME` when there is no explicit profile flag and no non-default sticky profile. In that case, later path resolution still flows through `get_hermes_home()`, which reads the existing environment variable first and only then falls back to `~/.hermes`.

This early timing is not cosmetic. `get_hermes_home()` is used all over the repo, and many modules resolve profile-aware paths at import time. Hermes therefore has to choose the home directory before those imports happen or the process may cache paths from the wrong profile.

### 2. Hermes loads the active profile's `.env`

After profile override, startup calls `load_hermes_dotenv()`.

The dotenv loader applies a two-layer rule:

1. load `<HERMES_HOME>/.env` with `override=True`
2. then load the repo-level `.env` only as a development fallback

That gives the active profile's secrets and toggles priority over stale shell exports. If a user env exists, the project `.env` only fills missing values. If no user env exists, the project `.env` can still seed a development checkout.

This is an important distinction: the configuration layer treats the profile-local `.env` as user-owned runtime state, while the repo `.env` is just a developer convenience.

### 3. Hermes bootstraps the home directory and default structure

Whenever config helpers run, `ensure_hermes_home()` makes sure the active home exists, secures directory permissions, creates the main subdirectories, and seeds a default `SOUL.md` if the profile does not already have one.

So `HERMES_HOME` is not just a lookup root. It is also the place where Hermes materializes first-run state.

### 4. `config.yaml` is loaded as persisted structure plus defaults

`load_config()` starts from a deep copy of `DEFAULT_CONFIG`, then merges the user's `config.yaml` on top of it. After the merge it normalizes older shapes, such as a root-level `max_turns`, and expands `${VAR}` references inside config values.

That behavior matters because Hermes treats `config.yaml` as persisted user intent, but it does not require the file to spell out every option. Missing keys are supplied from `DEFAULT_CONFIG`, so callers across CLI, gateway, cron, and setup can read one consistent config object.

This is also where the main ownership line between `config.yaml` and `.env` becomes clear:

- `config.yaml` owns structured, non-secret settings
- `.env` owns secrets and env-shaped values

The setup and `hermes config set` surfaces are built around that distinction. Public docs reinforce the same rule: API keys belong in `.env`; model choice, terminal backend, compression, and similar structured settings belong in `config.yaml`.

### 5. Higher-level flows persist through config helpers

`hermes_cli/setup.py` is a writer, not a second configuration system. It gathers user intent interactively, then persists changes through `save_config()` and `save_env_value()`. Likewise, `hermes config set` routes env-like keys to `.env` and other keys to `config.yaml`.

That means Hermes has one persistence layer even though it offers several user-facing ways to edit it.

## Precedence And Ownership Boundaries

The most important thing to keep straight is that the config layer defines the **sources**, while consuming subsystems define the **last-mile policy** for their own settings.

### Home, profile, and custom-path precedence

For selecting the active filesystem root, precedence is fixed:

1. explicit profile flag on this invocation
2. non-default sticky `active_profile`
3. preexisting `HERMES_HOME`
4. default `~/.hermes`

That rule is split across two layers:

- `_apply_profile_override()` can actively replace `HERMES_HOME` from profile state
- `get_hermes_home()` is the final resolver, so custom-path launches still work when startup leaves the env var alone

This page owns that combined rule.

### Environment fallback

For environment-shaped values, Hermes first projects the active `.env` into the process environment. After that:

- code that reads `os.environ` or calls `get_env_value()` sees the active profile's `.env` first
- the repo `.env` only exists as a fallback for development checkouts

This page owns that loading order.

### Persisted config versus runtime overrides

For structured settings, `load_config()` gives consumers:

1. built-in defaults from `DEFAULT_CONFIG`
2. overridden by persisted `config.yaml`
3. with `${VAR}` substitutions expanded against the current environment

But some runtime surfaces add one more layer on top. For example, provider resolution in [Provider Runtime](provider-runtime.md) can still apply explicit runtime requests before persisted config, and shells can still layer per-session flags on top of both. Those consumers own their own precedence rules. The config layer only guarantees that persisted config and env sources are available in a profile-scoped, consistent way.

That boundary matters because it prevents this page from claiming ownership over every policy decision in Hermes. Configuration chooses the substrate; runtime subsystems choose how to interpret it.

## Managed-Install Versus Local-Install Behavior

Hermes also distinguishes between a writable local install and a package-manager-managed install.

`hermes_cli/config.py` detects managed mode from either:

- `HERMES_MANAGED`
- a `.managed` marker file inside the active `HERMES_HOME`

When managed mode is active, config writers do not behave like a normal source checkout:

- `save_config()` refuses to rewrite `config.yaml`
- `save_env_value()` refuses to rewrite `.env`
- `run_setup_wizard()` refuses to run the normal interactive setup flow

Instead Hermes prints package-manager-specific guidance. The code currently recognizes Homebrew and NixOS explicitly:

- Homebrew users are directed toward `brew upgrade hermes-agent`
- NixOS users are directed toward `services.hermes-agent.settings` and `sudo nixos-rebuild switch`

In a local or source-based install, those guards are absent. Hermes can create `HERMES_HOME`, run setup, and persist changes directly through `config.yaml` and `.env`.

So the key distinction is not "managed installs use a different runtime." They still read the same profile-scoped paths. The distinction is that mutation ownership moves from Hermes's normal file writers to the external package-management workflow.

## Source Files

| File | Why it matters for this page |
| --- | --- |
| `hermes-agent/hermes_constants.py` | Defines `get_hermes_home()`, the canonical root for all profile-scoped path resolution. |
| `hermes-agent/hermes_cli/main.py` | Implements early profile override, sticky-profile fallback, and startup dotenv loading. |
| `hermes-agent/hermes_cli/profiles.py` | Defines named-profile storage, wrapper behavior, and path resolution for `HERMES_HOME`. |
| `hermes-agent/hermes_cli/env_loader.py` | Encodes the user-`.env` first, project-`.env` fallback behavior. |
| `hermes-agent/hermes_cli/config.py` | Owns defaults, home bootstrap, `config.yaml` merge/save, `.env` persistence, and managed-install checks. |
| `hermes-agent/hermes_cli/setup.py` | Shows that setup is a higher-level writer layered on top of the config helpers. |
| `hermes-agent/website/docs/user-guide/configuration.md` | Public user contract for `config.yaml`, `.env`, and config-management flows. |
| `hermes-agent/website/docs/user-guide/profiles.md` | Public user contract for profile isolation, aliases, and `HERMES_HOME`-based instance separation. |
| `hermes-agent/website/docs/developer-guide/architecture.md` | Confirms that profiles isolate config, memory, sessions, and gateway state through `HERMES_HOME`. |

## See Also

- [CLI Runtime](cli-runtime.md)
- [Provider Runtime](provider-runtime.md)
- [Prompt Assembly System](prompt-assembly-system.md)
- [Session Storage](session-storage.md)
- [Multi-Surface Session Continuity](../concepts/multi-surface-session-continuity.md)
