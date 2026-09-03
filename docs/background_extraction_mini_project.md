# Background Extraction Mini-project

This is a description of the different approaches to support the post-processing operation of background subtraction. These approaches are required as the traditional approach of measuring an empty cell and subtracting isn't possible for high-pressure measurements. 

## Background extraction methods

The general approach is to use the sample data themselves, attempt to distinguish sample and background and extract the latter. The scope of this work is to consider samples (or mixtures of samples) that are fully crystalline. Amorphous or liquid samples are out of scope. 

### Method 1: ClipPeaks

This implements the "rolling sphere" algorithm already employed to extract peaks from transmission monitor data. It is appropriate where nothing is known in advance of the sample, so everything that looks like a sharp peak will be treated as sample and everything else as background. 

The main parameter is the diameter of the "ball" and this will probably have to be tuned for each sample, so should be exposed (in some way) to user control. 

Important consideration: the resolution of different spectra in the various pgs are different. SNAPRed applies custom binning of spectra to reflect this so the initial assumption (to be tested) is that a ball size defined in bins will be applicable for all pgs. It will, however, be globally affected by operations such as `Resample` (ideas: cast the ball diameter in termsl of "native, unresampled" bin size and recalculated what is actually applied according to an intermediate resample operation)

### Method 2: Use crystal species artefacts to calculate where signal lies.

Consult "inSpectrum" for how this is applied as this was used to prototype the approach.

When crystal species artefacts are present, they can be used to calculate the d-spacing position of any peak. The difficulty is that pressure changes lattice parameters. The inspectrum approach is: a) find peaks first b) index them to expected phases (allowing that they will have moved due to pressure, use any provided information via EOS and experimental pressure range to constrain this) c) solve for the real, in situ unit cell parameters. 

Subsequently, calculate expected d-spacings for the insitu lattice, then filter list according to calculated peak intensities. 

Subsequently, peak width has to be estimated. This can be done by fitting observed peaks to obtain their estimated FWHM, then using this to define their extent: the full width where they are visible above background on both their left and right sides. Fitting is complicated where peaks overlap.

Note: varying resolution between spectra in a pgs has to be considered.

The final output is a list of excluded regions, everything else is considered background. The background is then determined by fitting a weighted spline to the input data, where weights are == 1 in background region and == 0 in peak regions. User can control spline smoothing, but we should calculated the best starting point, since we know the peak widths. scipy.interpolate.make_smoothing_spline has been used in exactly this way in SNAPRed and works well.

### Method 3: composite background.

This is built on the application of method 2 to multiple runs within a campaign and works in the case (corresponding to a bin masked DAC dataset) where the background is mostly pressure independent. The idea is that, as the peaks move with pressure, they reveal the background that was hidden under them. With sufficient input runs, up to 100% of the background can be revealled in this way. Our raw background is then the numerical average of all of the input runs, ignoring the excluded peak regions. This calculation is done in snapwrap.spectralTools.tools.compositeBackground.

In method 3, we will have to consider scenarios where we have <= 100% of background coverage. This is approached with smoothing and interpolation to fill any existing gaps. We need to support an option where both smoothing and interpolation are skipped: applicable when we have 100% or very close coverage.

## Applying background

backgrounds extracted by any of the above methods, should be treated as artefacts and stored for retrieval. As with cropping we can enable a "force recalculate" option and default to using existing backgrounds. We should only keep the most recent background instead of storing everything. The corresponding artefacts IDs should record the method that generated them. For method 1 and 2 the scope of the artefact is the run number from the data that the background was extracted from, for method 3, the scope is campaign.

Once an extracted background is available, by any of the above methods, it is applied by subtraction from the input data. The resultant spectra will have y-values equal to zero or even negative in some points. So, typically a constant must be added to ensure all y values are positive numbers. 

## Diagnostics

It's very useful to inspec extracted backgrounds, plotted on top of input data. We need to keep this option available. Let's assume the beta users will want to compare the extraction methods, so the diag workspaces with the extracted backgrounds need to be associated with method via their names.