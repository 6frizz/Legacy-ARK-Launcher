# Third-party notices

## TEK Launcher (tek_lib.py, tek_steamclient.py)

`tek_lib.py` and `tek_steamclient.py` in this repo are Python ports of
parts of **TEK Launcher**, a launcher for ARK: Survival Evolved by
**Nuclearistt**:

- Project: https://github.com/Nuclearistt/TEKLauncher
- Copyright (C) 2020 Nuclearist
- License: MIT (reproduced below)

Ported, with attribution, from TEK Launcher's C# sources:

- `Utils/VDFNode.cs` → the VDF (Valve KeyValues) parser in `tek_lib.py`
- `Steam/App.cs` (file-based detection) → Steam library detection in
  `tek_lib.py` (`libraryfolders.vdf` / `appmanifest_*.acf` parsing)
- `Servers/UdpClient.cs`, `Servers/Server.cs` → the A2S query engine
  in `tek_lib.py` (A2S_INFO / A2S_PLAYER / A2S_RULES)
- `Servers/Info.cs`, `Servers/Description.cs` → `ServerExtraInfo` /
  `ServerDescription` in `tek_lib.py`
- `ARK/MapCode.cs`, `ARK/DLC.cs`, `ARK/Mod.cs`, `ARK/Game.cs` (data
  tables) → the ARK data models in `tek_lib.py`
- `Utils/TEKSteamClient.cs` → `tek_steamclient.py`, ctypes bindings
  for TEK's native `libtek-steamclient-2.dll`. The DLL is TEK's own
  MIT-licensed library; it is **not bundled** with this repo. On first
  use the launcher downloads it from TEK's official release mirrors
  (teknology-hub.com / de.teknology-hub.com) into the launcher's data
  folder, the same way TEK Launcher itself does.

Deliberate divergences and exclusions:

- TEK's server query **rejects** servers that are not running
  TEKWrapper or that use BattlEye. This port never gates on either:
  vanilla servers are first-class.
- **Not ported at all:** `libtek-injector.dll` (process injection) and
  `libtek-game-runtime.dll` (injected Steamworks emulation), and the
  corresponding C# (`Utils/TEKInjector.cs`, the launch path in
  `ARK/Game.cs`). This launcher starts games only through its own
  existing route (Steam running + the installed build's own exe).
- TEK's raw Steam client interop (`Steam/Api.cs`, steamclient64.dll
  vtable calls) is not ported; `tek_lib.py`'s registry/file detection
  and `steam://` URLs cover the same needs.
- TEK's launcher self-updater (mirror downloads + self-replacing exe)
  is not ported; this launcher's configurable version.json updater
  fits its zip distribution.

### MIT License (TEK Launcher)

MIT License

Copyright (c) 2020 Nuclearist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
