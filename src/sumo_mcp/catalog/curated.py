"""Curated (tier-1) SUMO command metadata.

Hand-picked, industry-relevant subset of the full SUMO CLI surface
(inventoried in data/sumo-cli-inventory.md: 14 binaries + 583 tool scripts).
Everything not listed here is still reachable as tier-3 through runtime
discovery of $SUMO_HOME/tools — this table only adds descriptions and
categories that help an agent pick the right command.

Tool-script names are relative to $SUMO_HOME/tools using "/" separators
(e.g. "visualization/plot_net_dump.py").
"""
from __future__ import annotations

from typing import Dict, Tuple

# name -> (category, description)
CURATED_BINARIES: Dict[str, Tuple[str, str]] = {
    "sumo": ("simulation", "Headless microscopic traffic simulation engine (the core simulator)."),
    "sumo-gui": ("gui", "GUI variant of the simulator with visualization (needs a display)."),
    "netedit": ("gui", "Interactive network editor GUI for .net.xml files (needs a display)."),
    "netconvert": ("network", "Import/convert networks (OSM, OpenDRIVE, VISUM, Vissim, shapefiles) to SUMO format."),
    "netgenerate": ("network", "Generate abstract networks: grid, spider or random topologies."),
    "polyconvert": ("network", "Import polygons/POIs (OSM, shapefiles) for visualization backgrounds."),
    "duarouter": ("routing", "Shortest-path/dynamic-user-assignment routing; turns trips into routes."),
    "jtrrouter": ("routing", "Junction-turn-ratio based routing (no destination matrix needed)."),
    "marouter": ("routing", "Macroscopic user-assignment router over OD matrices."),
    "dfrouter": ("routing", "Derive routes from induction-loop detector flow measurements."),
    "od2trips": ("demand", "Convert OD (origin-destination) matrices into individual trips."),
    "activitygen": ("demand", "Generate demand from population/activity statistics."),
    "emissionsMap": ("emissions", "Produce emission maps over speed/acceleration/slope ranges."),
    "emissionsDrivingCycle": ("emissions", "Compute emissions for a given driving cycle."),
}

CURATED_TOOLS: Dict[str, Tuple[str, str]] = {
    # --- demand generation & calibration ---
    "randomTrips.py": ("demand", "Generate random trips for a network (the standard quick-demand tool)."),
    "routeSampler.py": ("demand", "Sample routes to match edge counts / turn counts (calibration from counts)."),
    "createVehTypeDistribution.py": ("demand", "Create vehicle-type distributions from parameter ranges."),
    "ptlines2flows.py": ("demand", "Convert public-transport line definitions into vehicle flows."),
    "assign/duaIterate.py": ("demand", "Iterative dynamic user assignment (duarouter+sumo loop until convergence)."),
    # --- OSM import pipeline ---
    "osmGet.py": ("network", "Download OSM data for a bounding box."),
    "osmBuild.py": ("network", "Build a SUMO network (netconvert+polyconvert) from downloaded OSM data."),
    "osmWebWizard.py": ("gui", "Browser-based interactive OSM import wizard (opens a browser/GUI)."),
    "tileGet.py": ("visualization", "Download map tiles as background images for the simulation view."),
    # --- network processing ---
    "net/netdiff.py": ("network", "Diff two networks; produces patch files loadable by netconvert."),
    "net/netcheck.py": ("network", "Check network connectivity (unreachable edges, disconnected components)."),
    "net/net2geojson.py": ("network", "Export a SUMO network to GeoJSON."),
    "district/gridDistricts.py": ("network", "Generate a grid of districts (TAZ) covering the network."),
    "edgesInDistricts.py": ("network", "Assign network edges to districts/TAZ polygons."),
    "generateBidiDistricts.py": ("network", "Generate bidirectional districts for edges."),
    # --- route processing ---
    "route/cutRoutes.py": ("routing", "Cut routes from a larger scenario down to a sub-network."),
    "route/routeStats.py": ("routing", "Compute statistics (length, duration) over a route file."),
    "route/route2OD.py": ("routing", "Aggregate routes into an OD (TAZ relation) matrix."),
    "route/sort_routes.py": ("routing", "Sort a route file by vehicle departure time (required by sumo)."),
    "route/addStops2Routes.py": ("routing", "Insert stops into existing routes/vehicles."),
    "route/implausibleRoutes.py": ("routing", "Detect and score implausible (detoured) routes."),
    "route/routecheck.py": ("routing", "Validate route files against a network."),
    "findAllRoutes.py": ("routing", "Enumerate all routes between given start/end edges."),
    "jtcrouter.py": ("routing", "Build routes from junction turn counts."),
    # --- traffic signals ---
    "tlsCycleAdaptation.py": ("signals", "Adapt traffic-light cycles/green splits to measured demand (Webster)."),
    "tlsCoordinator.py": ("signals", "Coordinate traffic-light offsets for green waves along routes."),
    "tls/tls_csv2SUMO.py": ("signals", "Convert CSV signal-plan definitions into SUMO TLS programs."),
    "tls/tls_csvSignalGroups.py": ("signals", "Convert between TLS programs and per-signal-group CSV plans."),
    # --- detectors & measurements ---
    "detector/flowrouter.py": ("detectors", "Derive flows and routes from detector measurements."),
    "detector/edgeDataFromFlow.py": ("detectors", "Convert detector flow CSV into edgeData files."),
    "detector/mapDetectors.py": ("detectors", "Map detector positions (x,y/lon,lat) onto network lanes."),
    # --- infrastructure generation ---
    "generateParkingAreas.py": ("infrastructure", "Generate parking areas along network edges."),
    "generateParkingAreaRerouters.py": ("infrastructure", "Generate rerouters so vehicles search alternative parking."),
    "generateRerouters.py": ("infrastructure", "Generate rerouters that divert traffic around closed edges."),
    "generateContinuousRerouters.py": ("infrastructure", "Generate rerouters that keep vehicles circulating forever."),
    "distributeChargingStations.py": ("infrastructure", "Distribute EV charging stations over the network."),
    # --- outputs & analysis ---
    "output/attributeStats.py": ("analysis", "Statistics (mean/min/max/percentiles) over any XML attribute."),
    "averageTripStatistics.py": ("analysis", "Run sumo N times with random seeds and average trip statistics."),
    "countEdgeUsage.py": ("analysis", "Count per-edge usage from route files."),
    "traceExporter.py": ("analysis", "Convert FCD output into other trace formats (NS2, GPX, KML, ...)."),
    "xml/xml2csv.py": ("analysis", "Convert any SUMO XML output to CSV."),
    "xml/csv2xml.py": ("analysis", "Convert CSV back to SUMO XML given a schema."),
    "runSeeds.py": ("simulation", "Run a configuration multiple times with different random seeds."),
    # --- visualization ---
    "visualization/plot_net_dump.py": ("visualization", "Color the network map by edgeData dump values."),
    "visualization/plotXMLAttributes.py": ("visualization", "Universal plotter for any XML attributes."),
    "visualization/plot_summary.py": ("visualization", "Plot time lines from summary output."),
    "visualization/plot_net_speeds.py": ("visualization", "Color the network map by allowed speeds."),
    "visualization/plot_tripinfo_distributions.py": ("visualization", "Histogram distributions from tripinfo output."),
    "plot_trajectories.py": ("visualization", "Plot time/space/speed trajectories from FCD output."),
    # --- imports beyond OSM ---
    "import/gtfs/gtfs2pt.py": ("network", "Import GTFS public-transport schedules into SUMO (stops, lines, vehicles)."),
    "import/vissim/convert_detectors.py": ("network", "Convert Vissim detector definitions to SUMO."),
    "import/visum/visum_mapDistricts.py": ("network", "Map VISUM districts onto a converted network."),
    # --- misc utilities ---
    "turn-defs/turnCount2EdgeCount.py": ("detectors", "Convert turn-count data into edge-count data."),
    "createScreenshotSequence.py": ("visualization", "Script sumo-gui to produce screenshot sequences for videos."),
}

# GUI-launching commands that must be blocked unless explicitly allowed.
GUI_COMMANDS = frozenset({"sumo-gui", "netedit", "osmWebWizard.py"})
