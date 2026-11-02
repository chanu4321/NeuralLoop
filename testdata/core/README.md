# Shared test cases for the two cores

The Mac's `NeuralLoopCore` (Swift) and the Windows app's `neuralloop_desktop/core` (Python) keep the same rules.
These files hold cases both test suites run, so the rules can't drift apart:

| File | Rule | Swift | Python |
|---|---|---|---|
| `fsrs.json` | FSRS-4.5 scheduling | `FSRS.grade` | `core.loop.grade` |
| `progress-merge.json` | merging progress.json from several devices | `StudyProgress.merged`, `mergedSameDevice` | `core.progress.merged`, `merged_same_device` |
| `prep-window.json` | the chapters prepared just ahead (spec 08) | `PrepWindow.make`, `hasWork` | `core.prep.window`, `Window.has_work` |
| `nudges.json` | whether Pip nudges, and with what | `Nudges.decide` | `core.nudges.decide` |

Run by `apple/Tests/NeuralLoopCoreTests/SharedCasesTests.swift` (`swift test`) and `windows/tests/test_shared_cases.py`
(`make test-windows`). Inputs are in the apps' own file formats (book.json, progress.json, settings.json's
`nudgeSettings` and `nudgeHistory`), so a case reads like what's on disk.

A rule changes in both cores in the same change, and its cases here with it. Add a case when a bug is found in either
core: it then guards both.
