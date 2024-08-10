
import ipapi

nfo = ipapi.location()
if isinstance(nfo, dict):
    lang = nfo["languages"].split(",")[0].split("-")[0]
    geo = nfo["country"]

print(lang)
print(geo)
