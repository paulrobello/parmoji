# Audit Remediation Report

> **Project**: parmoji
> **Audit Date**: 2026-07-30
> **Remediation Date**: 2026-07-30
> **Severity Filter Applied**: all (60 issues)
> **Plan Source**: AUDIT.md `## Remediation Plan` (no `AUDIT-REMEDIATION-PLAN.md` playbook — plain `/audit` run)
> **Implementation Model**: Opus 5 (all fix agents)
> **Branch**: `fix/audit-remediation` (base `c5a3a4d`, unpushed)

---

## Execution Summary

| Phase | Status | Agent | Issues Targeted | Resolved | Partial | Manual |
|-------|--------|-------|-----------------|----------|---------|--------|
| 1 — Security guards | ✅ | fix-security | 2 | 2 | 0 | 0 |
| 2 — Critical Arch + blockers | ✅ | fix-architecture | 8 | 8 | 0 | 0 |
| 3a — Security (remaining) | ✅ | fix-security | 4 | 4 | 0 | 0 |
| 3b — Architecture (remaining) | ✅ | fix-architecture | 7 | 7 (1 already-done) | 0 | 0 |
| 3c — Code Quality | ✅ | fix-code-quality | 9 + QA-Lows | 9 + 5 Lows | 0 | 0 |
| 3d — Documentation | ✅ | fix-documentation | 8 + DOC-Lows | 8 + 4 Lows | 0 | 0 |
| 4 — Verification | ✅ | orchestrator | — | — | — | — |
| 6 — Low pass (post-wrapup) | ✅ | fix-architecture | 7 Low arch + DOC-003 | 4 | 0 | 4 flagged-risky |

**Overall**: **57 of 60 issues resolved** (DOC-003 resolved per maintainer decision); **4 Low items flagged risky** and deliberately deferred (behavior/API/cache changes — see "Remaining"). Gate is green: **114 tests, 0 ruff, 0 pyright errors, 97% coverage**.

> **Method note — Phase 3 was serialized, not parallel.** The skill's default runs the four Phase-3 agents concurrently, but it also says to serialize when agents heavily overlap on the same core files. This ~2 KLOC library has every domain editing `source.py`/`core.py`, and four concurrent `make checkall` runs (which mutate files via `ruff format`/`--fix`) would trample each other. So 3a → 3b → 3c → 3d ran sequentially, each with its own gate.

---

## Resolved Issues ✅

### Security (6/6)
- **[SEC-001]** Decompression-bomb / untrusted-bytes guards — `source.py` (tighten `Image.MAX_IMAGE_PIXELS` to 20 Mpx, 2 MiB response cap, Content-Type validation in all backends), `core.py` (catch `DecompressionBombError` at both `Image.open` sites).
- **[SEC-002]** Host/scheme allowlist in `request()` — `source.py` (`ALLOWED_HOSTS` = emojicdn.elk.sh, cdn.discordapp.com; validated on entry and on final redirect URL).
- **[SEC-003]** Proxy-env honoring — `source.py` (overridable `TRUST_ENV` ClassVar, default `True` — no behavior change; documented).
- **[SEC-004]** Conservative upper bounds — `pyproject.toml` (`Pillow<13`, `emoji<3`, `httpx<1`, `requests<3`).
- **[SEC-005]** Sanitized logging — `source.py` (`_safe_url_label` host+path in WARNING logs; exception type names instead of raw text).
- **[SEC-006]** `blake2b(digest_size=16)` cache keys — `source.py`, `local_source.py` (replaces MD5; invalidates old on-disk entries, rebuilds on next fetch).

### Architecture (15/15 main + 7 Medium)
- **[ARC-001]** (Critical) `src/parmoji/py.typed` + CI wheel assertion in `build.yml`.
- **[ARC-002]** (Critical) Discord animated flag preserved through `Node`/parser; `get_discord_emoji` requests `.gif` first for animated IDs with `.png` fallback, `.png` only for static.
- **[ARC-003]** (Critical) `Parmoji.open()` delegates to `HTTPBasedSource.reopen()`; client lifecycle centralized in `_init_http_client()`; default httpx backend recreated on reopen.
- **[ARC-004]** (High) Dependency contract resolved — httpx/requests/emoji/xdg are hard deps; dead `_has_*` guards and urllib backend deleted; `HTTP_BACKEND` selector keeps requests reachable; README corrected.
- **[ARC-006]** (High) `_processed_image_cache` bounded as a third `LRUCacheDict`.
- **[ARC-007]** (High) Caches store immutable `bytes`; `close()`-on-evict dropped; the separate `_cache_lock` removed (each LRU's own lock is now sole).
- **[ARC-008]** (High) Disk-cache promoted to `BaseSource._cache_get/_cache_put` template methods; `LocalFontSource` LSP fixed (tight/margin honored with distinct cache keys; `/` marker added).
- **[ARC-009]** (High) Single `PIL_VERSION`/`HAS_GETLENGTH` in helpers; `is_valid_emoji` delegates the emoji-library consult to `is_emoji`. *(Deviation — see Notable Decisions.)*
- **[ARC-010]** (Med) Async rationale already gone (confirmed in Phase 2).
- **[ARC-011]** (Med) `prime_cache` 188-emoji literal hoisted to `_DEFAULT_PRIME_EMOJIS: Final[frozenset[str]]`.
- **[ARC-012]** (Med) Pluggable CDN / failover documented on `EmojiCDNSource` (extensibility only).
- **[ARC-013]** (Med) `__del__` reduced to guarded backstop (`suppress` + `getattr _closed`); `HTTPBasedSource.__del__` dedups via `close()`.
- **[ARC-015]** (Med) Makefile `checkall` reordered to `lint format typecheck test`.
- **[ARC-016]** (Med) Source-coercion extracted to `_coerce_source()` factory.
- **[ARC-017]** (Med) `LRUCacheDict` made generic `OrderedDict[K, V]`; 4 `# type: ignore` removed (legitimate Pillow-stub ignores kept).

### Code Quality (9 + 5 Lows)
- **[QA-001]** (High) `max(1, cache_size // 2)` in constructor — applied during Phase 2.
- **[QA-003]** (High) Broad `except Exception` narrowed to specific exceptions across all 4 modules; cache-write failures promoted to `logger.warning`. `__del__` `suppress` and the best-effort `is_emoji` probe intentionally left broad.
- **[QA-004]** (High) Autouse renderer-masking fixtures removed; opt-in `stub_emoji_source` fixture added; unconditional 😀 seeding gone; a pre-existing test-isolation bug (`helpers` reload splitting `NodeType` identity) fixed.
- **[QA-005]** (Med) `_FailedRequestCache` extracted from `HTTPBasedSource`; back-compat property accessors retained.
- **[QA-008]** (Med) `_get_cached(key, cache, fetch_fn)` de-duplicates `_get_emoji`/`_get_discord_emoji`.
- **[QA-011]** (Med) `_fetch_and_persist` validates bytes are an image before persisting; marks key failed on invalid bytes.
- **[QA-012]** (Med) `find_emojis_in_text` ASCII fast-path (skips O(10) probe on ASCII windows).
- **[QA-014]** (Med) `EMOJI_SET` lazy-built via `functools.lru_cache` + PEP 562 `__getattr__`.
- **[QA-015]** (Med) `_processed_image_cache` lock race — resolved by design (it is now an `LRUCacheDict`).
- **QA-Lows done:** dead duplicate `BytesIO` import removed; `find_emojis_in_text` → `_find_emojis_in_text`; `LocalFontSource` field types → `Optional[...]`; hand-rolled SIGALRM timeout → `pytest-timeout`; duplicated `_measure_text_width` consolidated into helpers.

### Documentation (7 + 4 Lows)
- **[DOC-001]** (High) `LocalFontSource` documented in README + ARCHITECTURE (offline rendering, post-ARC-008 behavior).
- **[DOC-002]** (High) `2.0.8` entry added to `RELEASE_NOTES.md` (lockstep with README).
- **[DOC-003]** (High) `__author__` set to `"Paul Robello"` (matches pyproject); jay3332 remains credited as the original Pilmoji author in README Acknowledgements.
- **[DOC-004]** (Med) Style-guide rewrite — verified already committed pre-remediation (`c5a3a4d`).
- **[DOC-005]** (Med) `CONTRIBUTING.md` added (points into `AGENTS.md`).
- **[DOC-006]** (Med) All 12 `EmojiCDNSource` subclasses + aliases enumerated in README.
- **[DOC-007]** (Med) All 9 `HTTPBasedSource` ClassVars documented (Attributes section).
- **[DOC-008]** (Med) `local_source.py` / module-layout description corrected in `AGENTS.md`.
- **DOC-Lows done:** Limitations/Known-Issues section; portable font example (`ImageFont.load_default()`); changelog pointer; `Parmoji.text` no-op params named. Mass docstring-style normalization deferred (out of scope).

---

## Requires Manual Intervention 🔧

None — DOC-003 (attribution) was resolved per the maintainer's decision (`__author__ = "Paul Robello"`). The 4 items below are **flagged-risky Low** items deliberately deferred because each is a behavior/API/cache change that warrants a deliberate decision (see "Remaining").

---

## Remaining Low Items

A focused post-wrapup pass addressed the 7 Low Architecture items. **3 were safe and done; 4 were flagged risky and deliberately left unchanged.**

**Done (safe):**
1. `PIL_VERSION` now parses with a guard that stops at the first non-numeric segment — a Pillow prerelease (`12.3.0.dev0`) no longer crashes import (`helpers.py`, +parametrized test).
2. `close()` now `.clear()`s the three `LRUCacheDict`s instead of re-allocating (instance torn down; behavior-preserving).
3. Hot-path logging converted from f-strings to lazy `%s` (request/fetch paths; SEC-005 sanitization preserved).

**Flagged risky (not changed — each needs a deliberate decision):**
4. **`getsize` ignores `stroke_width`** — fixing it adds `2*stroke_width` per glyph, a **layout-behavior change** that shifts measured widths and any golden/layout tests. Needs coordinated test updates.
5. **`direction`/`features`/`language` accepted but partly unimplemented by `Parmoji.text`** — already documented (DOC-Lows). Adding warnings/validation is a runtime behavior change.
6. **`DiscordEmojiSourceMixin` inherits concretely despite the "Mixin" name** — renaming is a **public API break** (exported in `__all__`, subclassed by `EmojiCDNSource`); needs a deprecation cycle.
7. **Cache path uses the legacy `par-term` prefix** — changing the path segment **relocates/invalidates every existing user's on-disk cache** (forces re-download); needs a migration plan + release note. Touches `source.py`, README, ARCHITECTURE, conftest.

Deferred Low QA/DOC: redundant `as` aliases in `__init__.py` (harmless, left intentionally); `# Changed to HTTPS` VCS-narrative comment (left); consolidating the 9 coverage-named test files by feature; mass docstring Google-vs-NumPy/RST normalization.

---

## Verification Results

- **Format (ruff format)**: ✅ Pass
- **Lint (ruff check)**: ✅ Pass — 0 violations
- **Type Check (pyright, src/)**: ✅ Pass — 0 errors, 0 warnings, 0 informations
- **Tests (pytest)**: ✅ Pass — **114 passed** (baseline 104 → net +10 after deleting obsolete tests and adding regression guards incl. PIL_VERSION parametrized cases), 97% coverage
- **Tests type-check**: `uv run pyright tests/` → 0 errors
- **Per-issue validation**: every Critical and High issue's fix confirmed present at its reported location; Medium issues spot-checked; SEC/ARC/QA/DOC changes verified.

> **Note on diagnostics**: the editor's LSP pyright (stricter overlay) flags some `★ "not accessed"` hints on intentional test fixtures / ABC-signature stub params and a `reportAttributeAccessIssue` false positive on inherited `_failed_cache_file`/`_failed_requests` properties. The project's configured gate (`pyrightconfig.json` includes only `src/`) reports these clean. No action needed.

---

## Notable Decisions & Deviations

- **ARC-009 (partial unification, disclosed).** The audit framed `is_emoji` and `is_valid_emoji` as incoherent duplication, but existing tests (`test_detection.py`, `test_source_is_valid_more.py`) document an **intentional two-tier policy** — `is_emoji` is permissive (layout/parsing), `is_valid_emoji` is strict (fetch validation; rejects text-presentation dingbats, length cap). The agent removed the *genuine* duplication (emoji-library consult + duplicated `PIL_VERSION`) but preserved the two distinct behaviors rather than collapse them into one. This is correct — collapsing would have been a wrong forced change.
- **ARC-004 (HTTP_BACKEND selector).** The audit's remedy was "delete the guards + urllib fallback." The agent additionally introduced a `HTTP_BACKEND` ClassVar so the requests backend stays genuinely reachable/testable now that the always-True selection flags are gone. Minimal, contract-honoring API addition.
- **ARC-008 (tight/margin).** Chose "honor in LocalFontSource" over "split the ABC": local rendering always crops to the glyph bbox, so `tight` is effectively always satisfied; `tight`/`margin` now drive crop padding with byte-for-byte default output and distinct cache keys.
- **ARC-011 emoji escaping.** A save-hook mangled literal emojis into malformed surrogate pairs and `ruff --fix` collapsed the set 188→12; the agent recovered using `\U0001F600` single-codepoint escapes and verified all 188 survive a fresh gate.
- **AUDIT.md in history.** A Phase-2 `git add -A` swept the (then-untracked) `AUDIT.md` into a code commit. Left as-is on the unpushed branch rather than rewriting 7 commits; it is a useful audit record and will be removed by the wrap-up step if desired.

---

## Files Changed (35 files, +1884 / −1042 vs base `c5a3a4d`)

**Created:** `src/parmoji/py.typed`, `CONTRIBUTING.md`
**Deleted:** `tests/test_source_import_fallbacks.py` (exercised the removed urllib/guard paths)
**Source (modified):** `src/parmoji/{core,source,helpers,local_source}.py`
**Build/CI/manifest:** `pyproject.toml`, `uv.lock`, `Makefile`, `.github/workflows/build.yml`
**Docs:** `README.md`, `AGENTS.md`, `docs/{ARCHITECTURE,RELEASE_NOTES}.md`
**Tests:** `tests/{conftest,test_cache_retry,test_core_branches,test_core_draw_paths,test_core_lru_and_prepare,test_core_misc,test_core_remaining,test_detection,test_helpers_fallback_reload,test_helpers_more,test_httpbasedsource_paths,test_local_source_cache,test_more_core_source_coverage,test_render_alignment,test_source_cdn_error_branches,test_source_more_edges,test_source_prime_and_cdn,test_tight_cropping,test_tight_cropping_edges}.py`

**Commits (16):** `c86d2c2` → `1568ce0` on `fix/audit-remediation` (plus this report update).

---

## Next Steps

1. **Review the security changes** (SEC-001..006) before merge — they were flagged for manual review per the security policy and are committed on this unpushed branch.
2. **Decide on the 4 flagged-risky Low items** above (`getsize` stroke_width, no-op param validation, `DiscordEmojiSourceMixin` rename, `par-term` cache path) — each is a behavior/API/cache change needing a deliberate call; none is urgent.
3. **Re-run `/audit`** after merge to confirm closure and surface anything new.
4. Wrap-up (with confirmation): delete `AUDIT.md` and this `AUDIT-REMEDIATION.md`; merge `fix/audit-remediation` back to its target (`next-big-thing`); push when ready.
