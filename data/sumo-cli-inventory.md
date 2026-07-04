# SUMO CLI Inventory

Generated on `2026-03-31` for this machine only.

## Scope

- Included: local SUMO binaries under `F:\sumo\bin`, launcher batch files, and CLI-capable scripts under `F:\sumo\tools`
- Excluded: `sumo-mcp` MCP interfaces and server tools
- Status basis: local filesystem scan plus direct `--help`/command probing

## Summary

- `SUMO_HOME`: `F:\sumo`
- Native executable CLIs in `F:\sumo\bin`: `14`
- Launcher batch files in `F:\sumo\bin`: `1`
- CLI-capable scripts under `F:\sumo\tools` (`.py`, `.bat`, `.cmd`): `583`
- Standalone root-level tool scripts in `F:\sumo\tools`: `31`
- Extra non-official CLI entrypoints detected on `PATH`: `2`

## Native Executable CLIs

| Command | Path | Role |
| --- | --- | --- |
| `sumo` | `F:\sumo\bin\sumo.exe` | Core microscopic, multi-modal traffic simulator |
| `sumo-gui` | `F:\sumo\bin\sumo-gui.exe` | GUI frontend for SUMO with CLI startup options |
| `netedit` | `F:\sumo\bin\netedit.exe` | GUI editor for SUMO networks, demand, and infrastructure |
| `netconvert` | `F:\sumo\bin\netconvert.exe` | Network importer and builder |
| `netgenerate` | `F:\sumo\bin\netgenerate.exe` | Synthetic network generator |
| `duarouter` | `F:\sumo\bin\duarouter.exe` | Shortest-path router and DUE computation |
| `jtrrouter` | `F:\sumo\bin\jtrrouter.exe` | Router based on junction turning ratios |
| `marouter` | `F:\sumo\bin\marouter.exe` | Macroscopic O/D assignment to SUMO routes |
| `od2trips` | `F:\sumo\bin\od2trips.exe` | O/D matrix importer to trips |
| `polyconvert` | `F:\sumo\bin\polyconvert.exe` | Polygon and POI importer |
| `activitygen` | `F:\sumo\bin\activitygen.exe` | Daily person trip/activity generator |
| `dfrouter` | `F:\sumo\bin\dfrouter.exe` | Route builder using detector values |
| `emissionsMap` | `F:\sumo\bin\emissionsMap.exe` | Emissions map generator |
| `emissionsDrivingCycle` | `F:\sumo\bin\emissionsDrivingCycle.exe` | Emissions computation over a driving timeline |

Common invocation pattern:

```powershell
sumo --help
netconvert --help
duarouter --help
```

## Launcher

| Command | Path | Role |
| --- | --- | --- |
| `start-command-line.bat` | `F:\sumo\bin\start-command-line.bat` | Starts a SUMO-oriented command shell environment |

## Standalone Tool Scripts

These are direct scripts located at the root of `F:\sumo\tools`. Typical invocation form:

```powershell
python F:\sumo\tools\randomTrips.py --help
python F:\sumo\tools\osmGet.py --help
```

Detected root-level scripts:

- `averageTripStatistics.py`
- `countEdgeUsage.py`
- `createScreenshotSequence.py`
- `createVehTypeDistribution.py`
- `distributeChargingStations.py`
- `edgesInDistricts.py`
- `extractTest.py`
- `fcdReplay.py`
- `findAllRoutes.py`
- `generateBidiDistricts.py`
- `generateContinuousRerouters.py`
- `generateLandmarks.py`
- `generateParkingAreaRerouters.py`
- `generateParkingAreas.py`
- `generateParkingLots.py`
- `generateRailSignalConstraints.py`
- `generateRerouters.py`
- `jtcrouter.py`
- `osmBuild.py`
- `osmGet.py`
- `osmWebWizard.py`
- `plot_trajectories.py`
- `ptlines2flows.py`
- `randomTrips.py`
- `routeSampler.py`
- `runSeeds.py`
- `stateReplay.py`
- `tileGet.py`
- `tlsCoordinator.py`
- `tlsCycleAdaptation.py`
- `traceExporter.py`

## Tool Script Families

All of the following are present under `F:\sumo\tools\<family>\...` and contain CLI-capable scripts or launchers.

| Family | Script Count |
| --- | ---: |
| `assign` | 10 |
| `averageTripStatistics.py` | 1 |
| `build_config` | 32 |
| `contributed` | 117 |
| `countEdgeUsage.py` | 1 |
| `createScreenshotSequence.py` | 1 |
| `createVehTypeDistribution.py` | 1 |
| `detector` | 11 |
| `devel` | 9 |
| `distributeChargingStations.py` | 1 |
| `district` | 7 |
| `drt` | 5 |
| `edgesInDistricts.py` | 1 |
| `emissions` | 3 |
| `extractTest.py` | 1 |
| `fcdReplay.py` | 1 |
| `findAllRoutes.py` | 1 |
| `game` | 6 |
| `generateBidiDistricts.py` | 1 |
| `generateContinuousRerouters.py` | 1 |
| `generateLandmarks.py` | 1 |
| `generateParkingAreaRerouters.py` | 1 |
| `generateParkingAreas.py` | 1 |
| `generateParkingLots.py` | 1 |
| `generateRailSignalConstraints.py` | 1 |
| `generateRerouters.py` | 1 |
| `import` | 23 |
| `jtcrouter.py` | 1 |
| `lib` | 1 |
| `net` | 27 |
| `neteditTestFunctions` | 40 |
| `osmBuild.py` | 1 |
| `osmGet.py` | 1 |
| `osmWebWizard.py` | 1 |
| `output` | 41 |
| `plot_trajectories.py` | 1 |
| `ptlines2flows.py` | 1 |
| `purgatory` | 25 |
| `randomTrips.py` | 1 |
| `route` | 29 |
| `routeSampler.py` | 1 |
| `runSeeds.py` | 1 |
| `shapes` | 6 |
| `simpla` | 8 |
| `stateReplay.py` | 1 |
| `sumolib` | 76 |
| `tileGet.py` | 1 |
| `tls` | 5 |
| `tlsCoordinator.py` | 1 |
| `tlsCycleAdaptation.py` | 1 |
| `traceExporter.py` | 1 |
| `traci` | 35 |
| `trigger` | 4 |
| `turn-defs` | 6 |
| `visualization` | 16 |
| `webWizard` | 2 |
| `xml` | 8 |

## Extra CLI Entrypoints Detected on PATH

These are not part of the stock `F:\sumo\bin` toolchain but were present in the current environment:

| Command | Path | Status |
| --- | --- | --- |
| `cli-anything-sumo.exe` | `D:\anaconda\Scripts\cli-anything-sumo.exe` | Broken: launching it raises `importlib.metadata.PackageNotFoundError: cli-anything-sumo` |
| `cli-anything-sumo-script.py` | `D:\anaconda\Scripts\cli-anything-sumo-script.py` | Broken: same missing package metadata issue |

## Practical Starting Set

If you want a working day-to-day CLI subset first, start with these:

- `sumo`
- `sumo-gui`
- `netconvert`
- `netgenerate`
- `duarouter`
- `od2trips`
- `polyconvert`
- `randomTrips.py`
- `osmGet.py`
- `osmBuild.py`
- `tlsCoordinator.py`
- `tlsCycleAdaptation.py`
- `routeSampler.py`

## Notes

- `SUMO_HOME` is set to `F:\sumo` on this machine.
- `F:\sumo\bin` is usable directly for native commands.
- `F:\sumo\tools` contains a much larger Python-script ecosystem than the stock binary set; many SUMO workflows depend on these scripts rather than only the `.exe` tools.
- This inventory is local-machine specific. If you upgrade or reinstall SUMO, the list may change.
