# Asset vs Artefact: concrete examples

This page is a short alignment note for `reduction_artefacts` design.

## Working definitions

- **Asset**: a persisted input, usually a file on disk.
- **Artefact**: an in-memory object derived from one or more assets, used by
  reduction/workflow logic.

This can be summarized as:

$$
\text{Asset (on disk)} \xrightarrow{\text{loader/builder}} \text{Artefact (in memory)}
$$

## Explicit examples

1. `cif file` $\rightarrow$ `crystalSpecies` object (built via
   `crystalSpecies.from_cif`, Mantid-backed; see
   `docs/crystal_species_refinement_plan.md`)
2. `nxs file` (NeXus) $\rightarrow$ Mantid `MaskWorkspace`
3. `swiss cheese .json` $\rightarrow$ SNAPRed swiss-cheese object
4. `eos file` (format TBD) $\rightarrow$ EOS object (type to be finalized)

## Where this is encoded in code

- `src/snapwrap/reduction_artefacts/asset_artefact_examples.py`
  - `list_asset_artefact_examples()` returns all four mappings
  - `build_example_artefact(slug, source_path)` builds concrete placeholder
    in-memory objects for each mapping

These are intentionally lightweight placeholders so semantics can be tested
without introducing Mantid/SNAPRed runtime dependencies into unit tests.
