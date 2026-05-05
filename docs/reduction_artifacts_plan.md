# Reduction artifacts

This project will create a module that collects artifacts to support a SNAPRed reduction workflow that is customized via hooks. Several different artifacts are envisaged and these may differ according to details of the experimental measurement. The core use case is to orchestate reduction for specific types of pressure cell

## Examples: 

* For DAC reduction to proceed, typical artifacts include: a bin of pixel mask. They could also include information on the sample composition to needed to facilitate background extraction.

* For PE reduction typical artifacts include a pixel mask and suffificient information to calculate an attenuation correction

## Requirements

The new module will provide a simple entry point where a standardised request will locate and/or manufacture the artifacts. It will have comprehensive tacking of failure modes (e.g. artifact cannot be constructed) and a mechaniusm for the subsequent reduction workflow to adapt to the reality of an incomplete artifact list.

In addition to orchestration of serving artifacts, the module will also need to create artifacts in addition to retrieving existing ones. 