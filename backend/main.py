import Millennium
import PluginUtils  # type: ignore

logger = PluginUtils.Logger()

import json
import os
import shutil

import requests
import httpx
import threading
import time
import re
import sys
import zipfile
import subprocess
if sys.platform.startswith('win'):
    try:
        import winreg  # type: ignore
    except Exception:
        winreg = None  # type: ignore

WEBKIT_DIR_NAME = "fwuc"
WEB_UI_JS_FILE = "fwuc.js"
CSS_ID = None
JS_ID = None
DEFAULT_HEADERS = {
    'Accept': 'application/json',
    'X-Requested-With': 'SteamDB',
    'User-Agent': 'https://github.com/BossSloth/Steam-SteamDB-extension',
    'Origin': 'https://github.com/BossSloth/Steam-SteamDB-extension',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
}
API_URL = 'https://extension.steamdb.info/api'
HTTP_CLIENT = None
DOWNLOAD_STATE = {}
DOWNLOAD_LOCK = threading.Lock()
STEAM_INSTALL_PATH = None

class Logger:
    @staticmethod
    def warn(message: str) -> None:
        logger.warn(message)

    @staticmethod
    def error(message: str) -> None:
        logger.error(message)

def GetPluginDir():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..'))

def Request(url: str, params: dict) -> str:
    response = None
    try:
        response = requests.get(url, params=params, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        return response.text
    except Exception as error:
        return json.dumps({
            'success': False,
            'error': str(error) + ' ' + (response.text if response else 'No response')
        })

def GetApp(appid: int, contentScriptQuery: str) -> str:
    logger.log(f"Getting app info for {appid}")

    return Request(
        f'{API_URL}/ExtensionApp/',
        {'appid': int(appid)}
    )

def GetAppPrice(appid: int, currency: str, contentScriptQuery: str) -> str:
    logger.log(f"Getting app price for {appid} in {currency}")

    return Request(
        f'{API_URL}/ExtensionAppPrice/',
        {'appid': int(appid), 'currency': currency}
    )

def GetAchievementsGroups(appid: int, contentScriptQuery: str) -> str:
    logger.log(f"Getting app achievements groups for {appid}")

    return Request(
        f'{API_URL}/ExtensionGetAchievements/',
        {'appid': int(appid)}
    )

class Plugin:
    def init_http_client(self):
        global HTTP_CLIENT
        if HTTP_CLIENT is None:
            try:
                logger.log('InitApis: Initializing shared HTTPX client...')
                HTTP_CLIENT = httpx.Client(timeout=10)
                logger.log('InitApis: HTTPX client initialized')
            except Exception as e:
                logger.error(f'InitApis: Failed to initialize HTTPX client: {e}')

    def close_http_client(self):
        global HTTP_CLIENT
        if HTTP_CLIENT is not None:
            try:
                HTTP_CLIENT.close()
            except Exception:
                pass
            HTTP_CLIENT = None
            logger.log('InitApis: HTTPX client closed')

    def _get_backend_path(self, filename: str) -> str:
        return os.path.join(GetPluginDir(), 'backend', filename)

    def _read_text(self, path: str) -> str:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ''

    def _write_text(self, path: str, text: str) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)


    def copy_webkit_files(self):
        webkitJsFilePath = os.path.join(GetPluginDir(), "public", WEB_UI_JS_FILE)
        steamUIPath = os.path.join(Millennium.steam_path(), "steamui", WEBKIT_DIR_NAME)
        
        # Create fwuc directory if it doesn't exist
        os.makedirs(steamUIPath, exist_ok=True)
        
        # Copy JavaScript file
        jsDestPath = os.path.join(steamUIPath, WEB_UI_JS_FILE)
        logger.log(f"Copying fwuc web UI from {webkitJsFilePath} to {jsDestPath}")
        try:
            shutil.copy(webkitJsFilePath, jsDestPath)
        except Exception as e:
            logger.error(f"Failed to copy fwuc web UI, {e}")

    def inject_webkit_files(self):
        # Inject JavaScript
        jsPath = os.path.join(WEBKIT_DIR_NAME, WEB_UI_JS_FILE)
        JS_ID = Millennium.add_browser_js(jsPath)
        logger.log(f"fwuc injected web UI: {jsPath}")

    def _front_end_loaded(self):
        self.copy_webkit_files()

    def _load(self):
        logger.log(f"bootstrapping fwuc plugin, millennium {Millennium.version()}")
        # Detect Steam install path via registry (fallback to Millennium.steam_path())
        try:
            detect_steam_install_path()
        except Exception as e:
            logger.warn(f'fwuc: steam path detection failed: {e}')
        self.init_http_client()
        self.copy_webkit_files()
        self.inject_webkit_files()

        Millennium.ready()  # this is required to tell Millennium that the backend is ready.

    def _unload(self):
        logger.log("unloading")
        self.close_http_client()

# ---------------- Module-level wrappers for frontend callable routes ----------------

def _backend_path(filename: str) -> str:
    return os.path.join(GetPluginDir(), 'backend', filename)

def _read_text(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''

def _write_text(path: str, text: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _ensure_http_client() -> None:
    global HTTP_CLIENT
    if HTTP_CLIENT is None:
        try:
            logger.log('InitApis: Initializing shared HTTPX client (module)...')
            HTTP_CLIENT = httpx.Client(timeout=10)
            logger.log('InitApis: HTTPX client initialized (module)')
        except Exception as e:
            logger.error(f'InitApis: Failed to initialize HTTPX client (module): {e}')


# --------------- Steam Install Path Detection and fwuc presence -----------

def detect_steam_install_path() -> str:
    global STEAM_INSTALL_PATH
    if STEAM_INSTALL_PATH:
        return STEAM_INSTALL_PATH
    # Try Windows registry first
    path = None
    try:
        if winreg is not None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                path, _ = winreg.QueryValueEx(key, 'SteamPath')
    except Exception:
        path = None
    if not path:
        try:
            path = Millennium.steam_path()
        except Exception:
            path = None
    STEAM_INSTALL_PATH = path
    logger.log(f'fwuc: Steam install path set to {STEAM_INSTALL_PATH}')
    return STEAM_INSTALL_PATH or ''

def HasfwucForApp(appid: int, contentScriptQuery: str = '') -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({ 'success': False, 'error': 'Invalid appid' })
    base = detect_steam_install_path() or Millennium.steam_path()
    candidate1 = os.path.join(base, 'config', 'stplug-in', f'{appid}.lua')
    candidate2 = os.path.join(base, 'config', 'stplug-in', f'{appid}.lua.disabled')
    exists = os.path.exists(candidate1) or os.path.exists(candidate2)
    logger.log(f'fwuc: HasfwucForApp appid={appid} -> {exists}')
    return json.dumps({ 'success': True, 'exists': exists })

def RestartSteam(contentScriptQuery: str = '') -> str:
    """Run the pre-shipped restart_steam.cmd in backend/. No generation, just execute."""
    backend_dir = os.path.join(GetPluginDir(), 'backend')
    script_path = os.path.join(backend_dir, 'restart_steam.cmd')
    if not os.path.exists(script_path):
        logger.error(f'fwuc: restart script not found: {script_path}')
        return json.dumps({ 'success': False, 'error': 'restart_steam.cmd not found' })
    try:
        # Launch a visible cmd window so user can see progress; the script ends with 'exit' to auto-close
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(['cmd', '/C', 'start', '', script_path], creationflags=DETACHED_PROCESS)
        logger.log('fwuc: Restart script launched')
        return json.dumps({ 'success': True })
    except Exception as e:
        logger.error(f'fwuc: Failed to launch restart script: {e}')
        return json.dumps({ 'success': False, 'error': str(e) })

# ---------------- fwuc add flow ----------------

def _set_download_state(appid: int, update: dict) -> None:
    with DOWNLOAD_LOCK:
        state = DOWNLOAD_STATE.get(appid) or {}
        state.update(update)
        DOWNLOAD_STATE[appid] = state

def _get_download_state(appid: int) -> dict:
    with DOWNLOAD_LOCK:
        return DOWNLOAD_STATE.get(appid, {}).copy()

def _download_zip_for_app(appid: int):
    _ensure_http_client()

    urls = [
        f"https://github.com/grom133114454/GameLibrary/archive/refs/heads/{appid}.zip",
        f"https://api.swa-recloud.fun/api/v3/file/{appid}.zip",
        f"https://furcate.eu/FILES/{appid}.zip",
        f"https://raw.githubusercontent.com/sushi-dev55/sushitools-games-repo/refs/heads/main/{appid}.zip",
        f"http://masss.pythonanywhere.com/storage?auth=IEOIJE54esfsipoE56GE4GE4&appid={appid}",
        f"https://mellyiscoolaf.pythonanywhere.com/{appid}",
        f"https://walftech.com/proxy.php?url=https%3A%2F%2Fsteamgames554.s3.us-east-1.amazonaws.com%2F{appid}.zip",
        f"https://github.com/SteamAutoCracks/ManifestHub/archive/refs/heads/{appid}.zip",
        f"https://github.com/Fairyvmos/bruh-hub/archive/refs/heads/{appid}.zip",
        f"https://github.com/hansaes/ManifestAutoUpdate/archive/refs/heads/{appid}.zip",
    ]

    dest_path = _backend_path(f"{appid}.zip")
    _set_download_state(appid, { 'status': 'checking', 'currentApi': None, 'bytesRead': 0, 'totalBytes': 0, 'dest': dest_path })

    for (i, url) in enumerate(urls):
        _set_download_state(appid, { 'status': 'checking', 'currentApi': '', 'bytesRead': 0, 'totalBytes': 0 })
        try:
            # Stream GET to be able to download if available
            with HTTP_CLIENT.stream('GET', url, follow_redirects=True) as resp:
                code = resp.status_code
                if code == 404:
                    continue
                if code != 200:
                    continue
                total = int(resp.headers.get('Content-Length', '0') or '0')
                _set_download_state(appid, { 'status': 'downloading', 'bytesRead': 0, 'totalBytes': total })
                with open(dest_path, 'wb') as f:
                    for chunk in resp.iter_bytes():
                        if not chunk:
                            continue
                        f.write(chunk)
                        st = _get_download_state(appid)
                        read = int(st.get('bytesRead', 0)) + len(chunk)
                        _set_download_state(appid, { 'bytesRead': read })
                logger.log(f"fwuc: Download complete -> {dest_path}")
                # Process and install the lua file from the zip
                try:
                    _set_download_state(appid, { 'status': 'processing' })
                    _process_and_install_lua(appid, dest_path)
                    _set_download_state(appid, { 'status': 'done', 'success': True, 'api': '' })
                except Exception as e:
                    logger.warn(f"fwuc: Processing failed -> {e}")
                    _set_download_state(appid, { 'status': 'failed', 'error': f'Processing failed: {e}' })
                return
        except Exception as e:
            continue

    _set_download_state(appid, { 'status': 'failed', 'error': 'Not available on any source' })

def _process_and_install_lua(appid: int, zip_path: str) -> None:
    """Open zip, locate numeric-only .lua (prefer <appid>.lua), comment out setManifestid lines, write to stplug-in."""
    base_path = detect_steam_install_path() or Millennium.steam_path()
    target_dir = os.path.join(base_path or '', 'config', 'stplug-in')
    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()
        candidates = []
        for name in names:
            pure = os.path.basename(name)
            if re.fullmatch(r"\d+\.lua", pure):
                candidates.append(name)
        chosen = None
        preferred = f"{appid}.lua"
        for name in candidates:
            if os.path.basename(name) == preferred:
                chosen = name
                break
        if chosen is None and candidates:
            chosen = candidates[0]
        if not chosen:
            raise RuntimeError('No numeric .lua file found in zip')

        data = zf.read(chosen)
        try:
            text = data.decode('utf-8')
        except Exception:
            text = data.decode('utf-8', errors='replace')

        # Comment out lines that start with setManifestid (ignoring leading whitespace)
        processed_lines = []
        for line in text.splitlines(True):
            if re.match(r"^\s*setManifestid\(", line) and not re.match(r"^\s*--", line):
                line = re.sub(r"^(\s*)", r"\1--", line)
            processed_lines.append(line)
        processed_text = ''.join(processed_lines)

        # Update state to installing and write to destination as <appid>.lua
        _set_download_state(appid, { 'status': 'installing' })
        dest_file = os.path.join(target_dir, f"{appid}.lua")
        with open(dest_file, 'w', encoding='utf-8') as out:
            out.write(processed_text)
        logger.log(f"fwuc: Installed lua -> {dest_file}")
        _set_download_state(appid, { 'installedPath': dest_file })

def StartAddViafwuc(appid: int, contentScriptQuery: str = '') -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({ 'success': False, 'error': 'Invalid appid' })
    logger.log(f'fwuc: StartAddViafwuc appid={appid}')
    # Reset state
    _set_download_state(appid, { 'status': 'queued', 'bytesRead': 0, 'totalBytes': 0 })
    t = threading.Thread(target=_download_zip_for_app, args=(appid,), daemon=True)
    t.start()
    return json.dumps({ 'success': True })

def GetAddViafwucStatus(appid: int, contentScriptQuery: str = '') -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({ 'success': False, 'error': 'Invalid appid' })
    state = _get_download_state(appid)
    return json.dumps({ 'success': True, 'state': state })

def AddDLCs(appid: int, contentScriptQuery: str = '') -> str:
    try:
        appid = int(appid)
    except Exception:
        return json.dumps({ 'success': False, 'error': 'Invalid appid' })

    logger.log(f'fwuc: AddDLCs for appid={appid}')

    # Ensure HTTP client is initialized
    _ensure_http_client()

    # Fetch app details from Steam API
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    try:
        if HTTP_CLIENT is not None:
            resp = HTTP_CLIENT.get(url, headers=DEFAULT_HEADERS)
            resp.raise_for_status()
            data = resp.json()
        else:
            return json.dumps({ 'success': False, 'error': 'HTTP client not available' })
    except Exception as e:
        logger.error(f'fwuc: Failed to fetch app details: {e}')
        return json.dumps({ 'success': False, 'error': f'Failed to fetch app details: {e}' })

    if str(appid) not in data or not data[str(appid)].get('success', False):
        return json.dumps({ 'success': False, 'error': 'App not found or API error' })

    app_data = data[str(appid)]['data']
    dlc_array = app_data.get('dlc', [])
    if not dlc_array:
        return json.dumps({ 'success': True, 'message': 'No DLCs found for this app' })

    # Get Steam path
    steam_path = detect_steam_install_path() or Millennium.steam_path()
    if not steam_path:
        return json.dumps({ 'success': False, 'error': 'Steam path not found' })

    steamtools_path = os.path.join(steam_path, 'config', 'stplug-in', 'Steamtools.lua')

    # Read existing content
    try:
        with open(steamtools_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        content = ''
    except Exception as e:
        logger.error(f'fwuc: Failed to read Steamtools.lua: {e}')
        return json.dumps({ 'success': False, 'error': f'Failed to read Steamtools.lua: {e}' })

    added_count = 0
    for dlc_id in dlc_array:
        if isinstance(dlc_id, int):
            dlc_appid = str(dlc_id)
            line = f"addappid({dlc_appid}, 1)"
            if line not in content:
                content += f"{line}\n"
                added_count += 1
                logger.log(f'fwuc: Added DLC {dlc_appid}')

    # Write back if changes were made
    if added_count > 0:
        try:
            with open(steamtools_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.log(f'Auto-added DLCs: Added {added_count} DLCs')
        except Exception as e:
            logger.error(f'fwuc: Failed to write Steamtools.lua: {e}')
            return json.dumps({ 'success': False, 'error': f'Failed to write Steamtools.lua: {e}' })

    return json.dumps({ 'success': True, 'message': f'Added {added_count} DLCs' })
