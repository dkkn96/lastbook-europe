# Lastbook Europe pilot

Lastbook Europe offers country maps built from OpenStreetMap, including [Italy](https://github.com/dkkn96/lastbook-europe/releases/tag/v0.1.0-alpha.2) and the smaller [Valle d’Aosta / Vallée d’Aoste](https://github.com/dkkn96/lastbook-europe/releases/tag/v0.1.0-alpha.1) pack. The setup selector lists the verified maps and the download size for each. The maps include streets, water, named places and points of interest such as pharmacies. The Valle d’Aosta pack also includes building footprints. Each library has one active map, and it changes when Lastbook restarts.

## Install on Mac

Download the [Lastbook Europe disk image](https://github.com/dkkn96/lastbook-europe/releases/tag/v0.1.0-alpha.4) for Apple Silicon and macOS 14 or later. Open it, drag **Lastbook Europe.app** to **Applications**, and launch the copied app. This preview uses an ad-hoc code signature. Apple has not notarized it. If macOS blocks it, see [Apple's guidance on opening apps](https://support.apple.com/en-us/102445).

Choose a country and leave **Map only** selected to download just that map and open it offline. You can choose a library or a model separately. To use an existing library, select it in setup. To switch areas later, open **Settings → Library and local AI → Choose map**.

The app verifies the SHA-256 of each download from GitHub before installation. Large maps use multiple release assets. Setup downloads those assets in order and installs them as one map. The [country map release](https://github.com/dkkn96/lastbook-europe/releases/tag/maps-europe-20261118) records each pack’s coverage and OpenStreetMap snapshot. The Spain pack follows Geofabrik’s mainland and Balearic extract. The Ireland pack covers the island, including Northern Ireland.

## Run from source

On Apple Silicon, create an isolated Python environment and run the desktop app from source.

```sh
python3 -m venv derived/europe-venv
derived/europe-venv/bin/python -m pip install -r packaging/requirements_macos.txt
LASTBOOK_PROFILE_DIR="$PWD/derived/europe-profile" derived/europe-venv/bin/python app/main.py
```

Setup offers the published map packs automatically. To use a map archive you already have, put its ZIP and matching JSON in `derived/regions/packs/`, or set `LASTBOOK_MAP_PACKS` to another directory. To use a library you already have, open a copy with `app/main.py --data /path/to/LastbookData`. Open **Library and local AI**, choose the map and restart when prompted. Use a copy if you want to preserve the active map in another Lastbook installation.

## Build the Mac disk image

On Apple Silicon with Xcode command line tools, CMake and uv, run `bash packaging/llm/build_llm_macos.sh` to build the bundled runner. Run `bash packaging/build_mac_python.sh` to build Python 3.11.18 and its dependencies for macOS 14. Then run `bash packaging/build_app_macos.sh`. The script prints the path to the verified disk image under `derived/app-build/mac/`.

The AI selector offers Gemma 4 26B A4B and Gemma 4 E4B. The downloaded weights are approximately 17 GB and 5 GB respectively. The source checkout needs the [Lastbook llama.cpp runner](../packaging/llm/) to answer with a model. Search and map use are available without weights. The E4B installation and switching logic was tested with fixture files. The full E4B file has not yet been tested on Metal in this fork.

## Use Qwen from a local model server

Lastbook can send chat requests to a separate OpenAI-compatible model server on this computer. Start the provider with a loopback address and load the model. Use the exact model ID returned by its `/v1/models` endpoint. Launch Lastbook with the following environment.

```sh
export LASTBOOK_LOCAL_AI=0
export SURVIVAL_MODEL_BASE=http://127.0.0.1:18792
export SURVIVAL_MODEL="<model ID listed by the local server>"
export SURVIVAL_MODEL_LABEL="Qwen3.8 27B Huihui Abliterated"
export LASTBOOK_PROFILE_DIR="$PWD/derived/europe-profile"
derived/europe-venv/bin/python app/main.py
```

For Apple Silicon, [Huihui Qwen3.8 27B Abliterated MLX 4-bit](https://huggingface.co/daguoagi/Huihui-Qwen3.8-27B-abliterated-MLX-4bit) is one option with MLX-VLM. [Huihui's GGUF build](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF) can be used with a compatible llama.cpp server. Use a provider that supports streaming tool calls to enable live document and map lookups. The in-app installer continues to offer the two bundled Gemma options.

The MLX build was tested on an Apple M4 Pro with MLX-VLM 0.7.12 and Transformers 5.14.0. Lastbook called the offline map to answer a question about Courmayeur in Italian. A separate question retrieved and cited a document in a synthetic test library.

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

### Whole Italy

Use the [dated national extract from Geofabrik](https://download.geofabrik.de/europe/italy-261116.osm.pbf). The build below includes the mainland and islands. It leaves out building footprints to reduce the size and keeps geometry on disk during processing.

```sh
python3 tools/build_region_map.py italy-261116.osm.pbf \
  --id IT-ALL --name "Italia" --bbox 6.55,35.43,18.62,47.14 \
  --search-language it --search-language de --search-language fr --search-language sl \
  --disk-index --no-buildings \
  --source https://download.geofabrik.de/europe/italy-261116.osm.pbf \
  --out derived/regions/italy-build
python3 tools/pack_region_map.py derived/regions/italy-build/IT-ALL --out derived/regions/packs
```

© OpenStreetMap contributors. The PBF and derived map database are made available under [ODbL 1.0](https://www.openstreetmap.org/copyright). Map builder and checker adapted from [Lastbook PR #80](https://github.com/Immortal-Protocols/lastbook/pull/80). The E4B model pin follows [Lastbook PR #9](https://github.com/Immortal-Protocols/lastbook/pull/9).
