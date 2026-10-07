# Architecture

`gui.py` → CustomTkinter UI/controller → bounded BackendClient queue → `Ditado Codex Service.exe` → patched Codex app-server → hosted voice service through WebRTC.

Source mode executes `live.py` with the current virtual environment interpreter. Portable mode executes the packaged service and never recursively launches the UI. Runtime assets/settings/build manifest resolve relative to the distribution root, not a temporary extraction directory.

Audio capture begins on an explicit start action, queues initial PCM during connection establishment, streams 20 ms chunks and retains up to the configured recording limit (maximum 120 seconds) in RAM. Capture loss is reported rather than silently accepted as complete audio. A fresh voice session is used for each recording; optional idle warm-up uses no microphone. Direct WebRTC avoids unnecessary ICE discovery; a STUN fallback is available for connectivity failures.

The UI uses generation IDs, connection epochs, ordered frame sequence IDs and terminal-result deduplication. Cancel invalidates older generations. Retained recordings can be replayed only through an explicit recovery action. Recovery never automatically inserts text.

The managed Codex account supplies authentication; no API key fallback is implemented. The broker validates the patched server hash and allowlists initialize/account-read/ephemeral-thread-start/realtime-start/stop. Unexpected local agent turn/item starts abort the broker. The fork's realtime admission gate is retired from initialization, with a regression test. Remote assistant replies can still be generated; the client ignores them instead of playing them.

A Windows Job Object scopes subprocess cleanup to this application. Hooks/tray events enqueue callbacks for the Tk thread. UI Automation reads focused element identity, process/control type, enabled/password/focus flags, not the field's value. Automatic insertion rechecks original focus and identity before SendInput. Unknown controls, password fields, terminals, control characters and multiline automatic input are refused. The native Edit fallback is restricted to same-process root/child controls.

Mini uses WS_EX_NOACTIVATE plus taskbar visibility styles. Approximately every 150 ms, the app reads the foreground executable name. Stable and Nightly T3 executables are accepted; ordinary browser windows whose titles mention T3 are not. Switching applications hides the mini and its tooltips; returning shows it without deliberately activating it. It is not docked to the T3 window.

Limitations: hosted experimental endpoint, unsigned binaries, no offline fallback in this release, no automatic updates, RAM-only recovery, no guarantee of quota/availability, and focus-check/Input delivery has the normal Windows race limitations. The binary hash is an integrity check against the supplied manifest, not publisher authentication. Verify the release checksum from GitHub and review the open source.
