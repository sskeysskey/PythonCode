from curl_cffi import requests as cffi
print(cffi.get("https://gdefud.com", impersonate="chrome124", timeout=15).status_code)