import hashlib
from typing import Optional
import requests
import base64
import json

try:
    import winreg
except Exception:
    winreg = None

_T = [103, 104, 112, 95, 81, 84, 48, 107, 106, 85, 90, 86, 78, 103, 56, 66, 90, 50, 88, 80, 98, 111, 115, 78, 100, 82, 80, 100, 97, 51, 85, 109, 73, 120, 49, 122, 72, 106, 86, 75]
_O = "grom133114454"
_R = "DB_FWU"

def _get_token():
    return ''.join(chr(x) for x in _T)

def _machine_guid() -> str:
    if winreg is None:
        return "unknown"
    # Try to read a stored DeviceId under HKCU (both registry views),
    # then fall back to MachineGuid under HKLM (trying 64-bit and 32-bit views).
    try_views = [0]
    # Add WOW64 flags if available on this Python build
    if hasattr(winreg, 'KEY_WOW64_64KEY'):
        try_views.append(winreg.KEY_WOW64_64KEY)
    if hasattr(winreg, 'KEY_WOW64_32KEY'):
        try_views.append(winreg.KEY_WOW64_32KEY)

    for view in try_views:
        try:
            access = winreg.KEY_READ | view if view else winreg.KEY_READ
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\FireWatchUnlocker", 0, access) as k:
                v, _ = winreg.QueryValueEx(k, "DeviceId")
                if v:
                    return str(v)
        except Exception:
            pass

    for view in try_views:
        try:
            access = winreg.KEY_READ | view if view else winreg.KEY_READ
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as k:
                v, _ = winreg.QueryValueEx(k, "MachineGuid")
                if v:
                    return str(v)
        except Exception:
            pass

    # Fallback: return a stable default GUID if none found
    return "182ac7b1-fc8c-4f5b-962c-02534c498dca"

def save_key_registry(key: str) -> bool:
    if winreg is None:
        return False
    try:
        try:
            k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\FireWatchUnlocker", 0, winreg.KEY_SET_VALUE | 0x0100)
            winreg.SetValueEx(k, 'AuthKey', 0, winreg.REG_SZ, str(key))
            winreg.CloseKey(k)
        except Exception:
            pass
        try:
            k32 = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\FireWatchUnlocker", 0, winreg.KEY_SET_VALUE | 0x0200)
            winreg.SetValueEx(k32, 'AuthKey', 0, winreg.REG_SZ, str(key))
            winreg.CloseKey(k32)
        except Exception:
            pass
        return True
    except Exception:
        return False

def read_key_registry() -> str:
    if winreg is None:
        return ''
    for acc in (0x0100, 0x0200):
        try:
            k = winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\FireWatchUnlocker", 0, winreg.KEY_READ | acc)
            val, _ = winreg.QueryValueEx(k, 'AuthKey')
            winreg.CloseKey(k)
            return str(val)
        except Exception:
            continue
    return ''

def validate_key(key: str) -> bool:
    if not key:
        return False
    
    try:
        import sys
        if hasattr(sys, 'gettrace') and sys.gettrace() is not None:
            return False
    except Exception:
        pass
    
    device = _machine_guid()
    headers = {
        'Authorization': f'token {_get_token()}',
        'User-Agent': 'FireWatchUnlocker'
    }
    
    try:
        url = f"https://api.github.com/repos/{_O}/{_R}/contents"
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            return False
        
        files = response.json()
        
        for file in files:
            file_name = file.get('name', '')
            if file_name.endswith('.json'):
                file_url = f"https://api.github.com/repos/{_O}/{_R}/contents/{file['name']}"
                file_response = requests.get(file_url, headers=headers)
                
                if file_response.status_code == 200:
                    file_data = file_response.json()
                    content = base64.b64decode(file_data['content']).decode('utf-8')
                    user_data = json.loads(content)
                    
                    if user_data.get('key_value') == key:
                        stored_device_id = user_data.get('device_id')
                        
                        if stored_device_id is None:
                            user_data['device_id'] = device
                            updated_content = json.dumps(user_data, indent=2)
                            encoded_content = base64.b64encode(updated_content.encode('utf-8')).decode('utf-8')
                            
                            update_payload = {
                                'message': f"Update device_id for user {user_data['username']}",
                                'content': encoded_content,
                                'sha': file_data['sha']
                            }
                            
                            update_response = requests.put(file_url, headers=headers, json=update_payload)
                            if update_response.status_code == 200:
                                save_key_registry(key)
                                return True
                        elif stored_device_id == device:
                            save_key_registry(key)
                            return True
                        else:
                            return False
        
        return False
        
    except Exception:
        return False

def has_valid_saved_key() -> bool:
    k = read_key_registry()
    return bool(k)

def has_saved_key() -> bool:
    return bool(read_key_registry())