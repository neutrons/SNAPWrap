# Reduction artefacts

This project will create a module that collects artefacts to support a SNAPRed reduction workflow that is customized via hooks. Several different artefacts are envisaged and these may differ according to details of the experimental measurement. The core use case is to orchestate reduction for specific types of pressure cell

## Examples: 

* For DAC reduction to proceed, typical artefacts include: a bin of pixel mask. They could also include information on the sample composition to needed to facilitate background extraction.

* For PE reduction typical artefacts include a pixel mask and suffificient information to calculate an attenuation correction

## Requirements

The new module will provide a simple entry point where a standardised request will locate and/or manufacture the artefacts. It will have comprehensive tacking of failure modes (e.g. artefact cannot be constructed) and a mechaniusm for the subsequent reduction workflow to adapt to the reality of an incomplete artefact list.

In addition to orchestration of serving artefacts, the module will also need to create artefacts in addition to retrieving existing ones. 