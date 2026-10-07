# Release validation — 0.3.0

Verified on Windows 10 x64 on 2026-10-07:

- **76 offline tests passed**, covering state/cancellation, stale and duplicate results, original focus checks, settings/dictionary, mini visibility, localization, native-service path selection and clean release manifests.
- Packaging regression tests prove undeclared debug logs, transcripts, environment files and developer settings are ignored, changed native build files are rejected, and unsafe paths/private filenames fail closed. The final ZIP is assembled in a fresh temporary directory from reviewed static file names and hashed PyInstaller COLLECT outputs.
- Real native window test: mini hides/shows without changing foreground focus; two controls remain within its bounds and taskbar/nonactivation styles are retained. Foreground executable matching is tested with mocked T3/other-process identities; this does not reproduce every possible T3 window workflow.
- Real native Unicode input into the validator's own Edit field passed with accented text and an emoji. Moving focus to a second field refused insertion. No input was sent to T3 or another application.
- Windows lifecycle validator passed: UI Automation in two threads, hotkey register/unregister, instance mutex and tray shutdown. No microphone opened.
- The **portable GUI and portable service**, without a `.venv` or source scripts in their distribution root, transcribed an included synthetic Portuguese WAV and recovered it after a simulated capture failure. First result arrived 5.76 seconds after stopping in that test. Actual microphone was not opened. Previous prepared-connection measurements were about 1.6–1.7 seconds; those are observations, not a latency guarantee.
- English normal UI, Preferences and mini were captured from isolated windows for visual inspection. A regression test verifies saving unrelated preferences does not reset English to Portuguese and dictated text stays verbatim.
- The shipped patched Rust server previously passed its targeted `dictation_fork` regression test (one selected test). The complete Rust suite and a fresh clean-room Rust rebuild were not rerun for this release.

Not claimed as tested: Windows 11, every input device, real speech accuracy for other users, long continuous use, every firewall/network failure, or actual user-field insertion in every T3 build. The owner's earlier real recordings worked, but synthetic tests do not replace those scenarios. The release is explicitly experimental.

Online validation requires your own account and can consume quota. Do not upload login files or private recordings in issues. Automated offline GitHub checks require no credentials or live service.
