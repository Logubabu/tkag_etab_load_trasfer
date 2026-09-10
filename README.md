# ETABS → RAM Concept Load Transfer

Project-specific utility prepared around the supplied ETABS/RAM Concept workflow.

## What it does

1. Attaches to an already-running ETABS model through the CSI API.
2. Forces ETABS API output units to **kN-m-C** (`eUnits = 6`).
3. Reads the selected story.
4. Transfers:
   - shell/area uniform loads → RAM Concept `AreaLoad`
   - frame distributed force loads → RAM Concept `LineLoad`
   - joint force loads → RAM Concept `PointLoad`
   - frame point force loads → RAM Concept `PointLoad`
5. Maps ETABS load-pattern names to RAM Concept standard loading layers.
6. Skips self-weight by default to prevent double counting RAM Concept self-dead.
7. Creates a **new CPT copy**; it never overwrites the original.
8. Produces a transfer JSON report and optional CSV audit file.

## Important project rules

- The supplied `ram.cpt` confirms these RAM Concept internal scales:
  - plan coordinate: `10,000 / m`
  - point force: `1,000 / kN`
  - line force: `0.1 / (kN/m)`
  - area force: `1e-5 / (kN/m²)`
  - moment: `10,000,000 / (kN·m)`
- Area polygons are written using RAM Concept `MultiPoint` encoding.
- Unmatched ETABS load patterns are **not transferred automatically**. They appear as REVIEW until you add/edit a regex mapping rule in `config.json`.
- Non-global/local-axis cases that cannot be transformed safely are flagged instead of silently guessed.
- Area load Local-3 is supported using the shell polygon normal.
- Global X, Y, Z and Gravity directions are supported directly.
- Frame local-axis distributed loads are flagged for review in this version.

## First run

1. Install Python 3.10+ / 3.11+ on the Windows workstation that has ETABS and RAM Concept.
2. Run `install.bat` once.
3. Open ETABS and open the required `.EDB` model.
4. Run `run.bat`.
5. Click **Attach ETABS**.
6. Choose the floor/story.
7. Click **Extract Story Loads** and review the list.
8. Select your RAM Concept `.cpt` template.
9. Click **Create RAM CPT Copy**.
10. Open the newly-created CPT in RAM Concept and visually verify the loading plans before design.

## Mapping for Dubai/PT projects

Default regex mapping:
- SELF WT / SELF WEIGHT → skip
- SDL / SIDL / SUPER / FINISH / PARTITION / WALL / CLADDING / DEAD → Other Dead Loading
- PARK → Live (Parking)
- ROOF LIVE → Live (Roof)
- STORAGE → Live (Storage)
- LIVE / LL → Live (Reducible)

Edit `config.json` when a project uses different load-pattern names.

## Coordinate alignment

If ETABS and RAM Concept do not share the same plan origin, edit:
```json
"coordinate_transform": {
  "origin_x_m": 0.0,
  "origin_y_m": 0.0,
  "rotation_deg": 0.0,
  "mirror_x": false,
  "mirror_y": false
}
```

The transform is applied before RAM Concept scaling.

## Validation procedure

Before using the generated CPT for production design:
1. Compare ETABS load-pattern totals with the exported CSV.
2. In RAM Concept, display each loading layer individually.
3. Spot-check at least one point, line and area load for:
   - location
   - sign
   - magnitude
   - loading layer
4. Confirm self-dead is not duplicated.
5. Confirm the target story geometry uses the same origin/rotation.
6. Keep the JSON transfer report with the design package.

This first release deliberately flags questionable assignments rather than making an unsafe assumption.


## v2 direct-file modes

**EDB mode (recommended for production):** select the `.EDB`. The tool connects to a running ETABS instance or starts ETABS automatically, calls `SapModel.File.OpenFile`, sets kN-m-C units, and extracts the selected story by API. You do not need to open the model manually first.

**E2K mode (direct text):** select an exported `.e2k` or `.$et`. ETABS does not need to run. The parser reads common story, point, frame, area and load tables. Because E2K field labels can vary by ETABS generation, it creates an `.e2k_diagnostic.json` and refuses to guess unsupported lines. Use EDB mode as the production route until an E2K from the exact office ETABS version has been calibrated.


## v3 API connection fix

If EDB mode says "API not connected":

1. Run `install.bat` again.
2. Run `TEST_ETABS_API.bat`.
3. Prefer 64-bit Python when ETABS is 64-bit.
4. Do not run ETABS as Administrator while running this tool normally, or vice versa. Both applications should use the same privilege level.
5. If an ETABS instance is already open, v3 tries:
   - pywin32 `GetActiveObject`
   - `ETABSv1.Helper.GetObject` with pywin32
   - `ETABSv1.Helper.GetObject` with comtypes
6. If ETABS is not open, v3 tries:
   - `ETABSv1.Helper.CreateObjectProgID` with pywin32
   - `ETABSv1.Helper.CreateObjectProgID` with comtypes
   - legacy direct ProgID startup

The error dialog now contains the full connection-attempt log. Copy that log back into ChatGPT if connection still fails.


## v4 — story load extraction fix

Critical correction:
Python CSI COM responses often return ByRef outputs directly. For example,
`GetNameListOnStory` is commonly exposed as `(NumberNames, Names)`.
The previous build could misinterpret `NumberNames` as an API error code and
therefore return zero objects. v4 treats it correctly as an output count.

v4 also retries getter functions with explicit ByRef placeholders for ETABS
installations whose COM wrapper requires the full argument list.

Use `TEST_STORY_LOADS.bat` to verify:
- story list
- area count
- frame count
- point count
- first 50 extracted load assignments
- API diagnostic log

The GUI now includes `Story Diagnostics`.
"# tkag_etab_load_trasfer" 
