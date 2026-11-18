# Lastbook Europe pilot

The pilot covers Valle d’Aosta / Vallée d’Aoste, Italy. It has offline streets, building footprints, water, named places and points such as pharmacies. The place index includes Italian and French names where OpenStreetMap records them. The snapshot has no street-address index, elevation tiles or route planner. A region replaces the active map set when Lastbook restarts.

## Open the pilot

On Apple Silicon, create an isolated Python environment and run the desktop app from source.

```sh
python3 -m venv derived/europe-venv
derived/europe-venv/bin/python -m pip install -r packaging/requirements_macos.txt
LASTBOOK_PROFILE_DIR="$PWD/derived/europe-profile" derived/europe-venv/bin/python app/main.py
```

Put both pilot files, `Lastbook-Map-IT-23.zip` and `Lastbook-Map-IT-23.json`, in `derived/regions/packs/` before opening Setup. You can use a different folder with `LASTBOOK_MAP_PACKS`. Select the region in **Choose a map**, then choose the library and model independently. To use a library you already have, open a copy with `app/main.py --data /path/to/LastbookData`. Open **Library and local AI**, choose the map and restart when prompted. Use a copy if you want to preserve the active map in another Lastbook installation.

The AI selector offers Gemma 4 26B A4B and Gemma 4 E4B. The downloaded weights are approximately 17 GB and 5 GB respectively. The source checkout needs the [Lastbook llama.cpp runner](../packaging/llm/) to answer with a model. Search and map use are available without weights. The E4B installation and switching logic was tested with fixture files. The full E4B file has not yet been tested on Metal in this fork.

## Build and check a map pack

Install the Python package `osmium==4.3.2` in the build environment. Download an OSM PBF extract and keep the build report to record the exact input hash. The regional builder itself runs offline.

```sh
python3 tools/build_region_map.py valle-aosta.osm.pbf \
  --id IT-23 --name "Valle d’Aosta / Vallée d’Aoste" \
  --bbox 6.75,45.40,8.06,46.02 --search-language it --search-language fr \
  --out derived/regions/build
python3 tools/check_region_map.py derived/regions/build/IT-23 \
  --engine --find Aosta --find Courmayeur --near 45.737,7.320
python3 tools/pack_region_map.py derived/regions/build/IT-23 --out derived/regions/packs
```

The pilot input came from [OpenStreetMap France](https://download.openstreetmap.fr/extracts/europe/italy/valle_aosta-latest.osm.pbf). Its PBF header reports `2026-11-17T01:00:49Z`, and its SHA-256 is `be7ffe76372ed3bd83b45434b4c8f3246022df7e10cd8b6d405180aee7942fc1`. The URL rolls forward as the source publishes new extracts.

© OpenStreetMap contributors. The PBF and derived map database are made available under [ODbL 1.0](https://www.openstreetmap.org/copyright). Map builder and checker adapted from [Lastbook PR #80](https://github.com/Immortal-Protocols/lastbook/pull/80). The E4B model pin follows [Lastbook PR #9](https://github.com/Immortal-Protocols/lastbook/pull/9).
