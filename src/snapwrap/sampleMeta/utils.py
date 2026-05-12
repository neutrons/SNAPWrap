# This module arose as a way to keep track of crystalline phases contributing to scatter in a diffraction pattern
# These are referred to as "species" and described by the class `crystalSpecies`.  Workspace Handles have an attribute
# crystalSpeciesList, which allows to associate multiple crystal species with a given workspace.
# This is frequently necessary (e.g. to represent sample and gasket) 

import json
from pathlib import Path

from mantid.simpleapi import *
from mantid.simpleapi import GetIPTS, LoadCIF, CreateSampleWorkspace, DeleteWorkspace, mtd
from mantid.geometry import CrystalStructure, ReflectionGenerator, ReflectionConditionFilter, SpaceGroupFactory
import numpy as np
from scipy.optimize import least_squares

# from snapwrap.wrapConfig import WrapConfig
# from snapwrap.SEEMeta.material import material
# from snapwrap.SEEMeta.db import engine
import importlib
import snapwrap.sampleMeta.latticeFittingFunctions as lff
importlib.reload(lff) #is this needed?


def _mantidScattererStrings(crystalStructure):
    """Return a list of Mantid-style scatterer strings from a CrystalStructure.

    Mantid's ``CrystalStructure.getScatterers()`` already returns a sequence of
    space-separated strings of the form ``"Element x y z occ uiso"``.  We simply
    normalise whitespace so we can re-join them with the ``"; "`` delimiter that
    the ``CrystalStructure`` constructor expects on input.
    """
    return [" ".join(str(s).split()) for s in list(crystalStructure.getScatterers())]


class crystalReflection:

    def __init__(self,
                hkl,
                dObs=None,
                extentOverPosition=None):
        
        self.hkl = hkl #
        self.h = hkl[0]
        self.k = hkl[1]
        self.l = hkl[2]
        self.dObs = dObs
        self.extentOverPosition = extentOverPosition #full extent of peak divided by its position

    def to_dict(self):
        return self.__dict__ #returns a json string of attributes

    @classmethod
    def from_dict(cls, d):
        return cls(
            hkl = d["hkl"],
            dObs = d["dObs"],
            extentOverPosition=d["extentOverPosition"] 
        )

class unitCell:

    def __init__(self,crystalSystem):

        allowedSystems = ['cubic','tetragonal','orthorhombic','hexagonal','trigonal','monoclinic','triclinic']
        if crystalSystem.lower() not in allowedSystems:
            raise ValueError(f"ERROR: crystal system {crystalSystem} not supported")
            return        

        #standardise case
        self.crystalSystem = crystalSystem.lower()
        
        #populate lattice params I can using crystalSystem, otherwise create and set equal to zero
        if self.crystalSystem in ['cubic','tetragonal','orthorhombic']:
            self.alpha = 90.0
            self.beta = 90.0
            self.gamma = 90.0
            
        elif self.crystalSystem in ['hexagonal','trigonal']:
            self.alpha = 90.0
            self.beta = 90.0
            self.gamma = 120.0 #TODO: manage different unique axes
        elif self.crystalSystem == 'monoclinic':
            self.alpha = 90.0
            self.beta = 90.0
            self.gamma = 0.0

        self.a = 0.0
        self.b = 0.0
        self.c = 0.0

        #define minimum number of reflections to determine unit cell params
        if self.crystalSystem == "cubic":
            self.minRefs = 1
        elif self.crystalSystem in ["tetragonal","trigonal","hexagonal"]:
            self.minRefs = 2
        elif self.crystalSystem == "orthorhombic":
            self.minRefs = 3  
        elif self.crystalSystem == "monoclinic":
            self.minRefs = 4
        elif self.crystalSystem == "triclinic":
            self.minRefs = 6

    def _print(self):

        print(f"a: {self.a:.4f} b: {self.b:.4f} b: {self.c:.4f} ")
        print(f"alpha: {self.alpha:.1f} beta: {self.beta:.1f} gamma: {self.gamma:.1f} ")
        print(f"crystal system: {self.crystalSystem}")

class crystalSpecies:
    # a workspace can hold multiple scattering phases contributing to a spectrum, here called "species".
    # the construction of this class reflects how it will be created in the field. We assume that the
    # user at least knows the space group 

    #: Schema version for ``to_dict`` / ``from_dict`` round-trips.  Bumped when
    #: persisted attributes are added or renamed.  ``from_dict`` remains tolerant
    #: of older versions (or no version field at all).
    SCHEMA_VERSION = 1

    #: Roles this species can play in a reduction workflow.  ``"sample"`` is the
    #: thing being studied; ``"calibrant"`` is a phase with a well-known EOS used
    #: to deduce sample conditions (e.g. tungsten in a DAC).
    ALLOWED_ROLES = ("sample", "calibrant")

    def __init__(self,
                spaceGroup,
                observedReflections,
                name = None, #a name for this species
                scatterers = "",
                dLimits = None, #fraction of maximum intensity to use as threshold for d-spacing generation
                cifPath = None, #optional provenance: path to the CIF this species was seeded from
                role = "sample", #"sample" or "calibrant"
                eos = None): #optional EquationOfState (snapwrap.sampleMeta.eos), attached for refinement workflows
        
        # spaceGroups is string with H-M space group
        # observedReflections is a list of crystalReflection objects
        # name is a string
        # scatterers is a mantid-style string of atomic positions, occupancies etc.

        # keep track of what valid information is available
        self.valid = {
            "spaceGroup" : False,
            "unitCell" : False,
            "scatterers" : False
        }

        #support supplying crystal system inplace of space group
        allowedSystems = ['cubic','tetragonal','orthorhombic','hexagonal','trigonal','monoclinic','triclinic']
        if spaceGroup.lower() in allowedSystems:
            self.crystalSystem = spaceGroup.lower()
            self.spaceGroup = ""
            self.valid["spaceGroup"] = False
        else:
            # try to identify crystal system from space group
            self.spaceGroup = spaceGroup  
            self._systemFromSG()

        self.name = name
        self._validateScatterers(scatterers)

        self.observedReflections = observedReflections
        self.nRefs = len(self.observedReflections)

        self._setExtentOverPosition()

        #attempt to build unitCell from observed reflection
        self.unitCell = self._cellFromReflections()

        #attempt to build crystalStructure object
        self.hasCrystalStructure = self._buildCrystalStructure()

        #encountered a need to specify d-range to use when calculating d-spacings
        self.dLimits = dLimits

        # Provenance + role + (optional) equation of state.  These travel with the
        # species through to_dict/from_dict and feed the future refinement bridge
        # (see docs/crystal_species_refinement_plan.md, Phases B–D).
        self.cifPath = str(cifPath) if cifPath is not None else None
        if role not in self.ALLOWED_ROLES:
            raise ValueError(
                f"Invalid role {role!r}; expected one of {self.ALLOWED_ROLES}"
            )
        self.role = role
        self.eos = eos

    def _systemFromSG(self):

        try: 
            sg = SpaceGroupFactory.createSpaceGroup(self.spaceGroup)
        except:
            raise ValueError(f"Invalid Hermann-Maugiun symbol: {self.spaceGroup}")
            self.valid["spaceGroup"] = False
            return

        SGNumber = sg.getNumber()
        if 1 <= SGNumber <= 2:
            self.crystalSystem = "triclinic"
        elif 3 <= SGNumber <= 15:
            self.crystalSystem = "monoclinic"
        elif 16 <= SGNumber <= 74:
            self.crystalSystem = "orthorhombic"
        elif 75 <= SGNumber <= 142:
            self.crystalSystem = "tetragonal"
        elif 143 <= SGNumber <= 167:
            self.crystalSystem = "trigonal"
        elif 168 <= SGNumber <= 194:
            self.crystalSystem = "hexagonal"
        elif 195 <= SGNumber <= 230:
            self.crystalSystem = "cubic"

        self.valid["spaceGroup"] = True

    def _setExtentOverPosition(self):

        N = 0
        extentOverPosition = 0.0
        for reflection in self.observedReflections:
            if reflection.extentOverPosition is not None:
                N += 1
                extentOverPosition += reflection.extentOverPosition
        
        if N == 0:
            self.extentOverPosition = None
        else:
            self.extentOverPosition = extentOverPosition/N # set to average of observed values

        return


    def _cellFromReflections(self):
    
        cell = unitCell(self.crystalSystem) #draft unit cell with empty values
        reflectionList = self.observedReflections

        #TODO count independent reflections and check there are enough.
        nRef = len(reflectionList)
        if nRef >= cell.minRefs:
            pass
            # print(f"{len(reflectionList)} reflections provided. This is sufficient for {cell.crystalSystem} system (assuming independence).")
        else:
            print(f"Error: you provided {nRef} refs, but {cell.minRefs} are required for {cell.crystalSystem} system")
            return

        #check that crystalSystem is supported: 

        # allowedSystems = ['cubic','tetragonal','orthorhombic','hexagonal','trigonal','monoclinic','triclinic']
        allowedSystems = ['cubic','hexagonal','trigonal']
        if self.crystalSystem.lower() not in allowedSystems:
            # Don't raise: a from_cif()-seeded crystalSpecies has a perfectly good
            # CIF-derived unit cell that we must NOT clobber just because we can't
            # *re-fit* it from observed reflections in this system.  Log + return
            # None and leave any existing cell intact.  See Phase A3 of
            # docs/crystal_species_refinement_plan.md.
            print(
                f"WARNING: cell-from-reflections refinement not implemented for "
                f"crystal system '{self.crystalSystem}'. Existing unit cell (if any) "
                f"will be preserved."
            )
            self.valid["unitCell"] = False
            return None

        #need to handle each system separately
        if cell.crystalSystem == "cubic":

            initialGuess = 5.0 # guess at a lattice param
            result = least_squares(lff.residual_cubic, initialGuess, args = (reflectionList,))

            if result.success:
                a = result.x[0]
                cell.a = a
                cell.b = a
                cell.c = a
                self.valid["unitCell"] = True
                return cell
            else:
                self.valid["unitCell"] = False
                print("Fit failed")

        if cell.crystalSystem in ["trigonal","hexagonal"]:

            #simple approach was not giving satisfying results, so use a randomized
            #search to improve chances.

            num_trials=100
            a_bounds=(1.0,10.0)
            c_bounds=(1.0,10.0)


            best_result = {
                "a":None,
                "c":None,
                "residual":np.inf,
                "success":False
            }

            for trial in range(num_trials):
                # Generate random initial guesses within bounds
                initial_a = np.random.uniform(*a_bounds)
                initial_c = np.random.uniform(*c_bounds)
                initial_guess = [initial_a, initial_c]

                try:
                    # Perform least squares fitting
                    result = least_squares(
                        lff.residual_hex,
                        initial_guess,
                        args=(reflectionList,),
                        bounds=([a_bounds[0], c_bounds[0]], [a_bounds[1], c_bounds[1]])
                    )

                    # Check if the fit was successful and track the best result
                    if result.success:
                        residual_sum = np.sum(np.square(result.fun))  # Sum of squared residuals
                        if residual_sum < best_result["residual"]:
                            best_result.update({
                                "a": result.x[0],
                                "c": result.x[1],
                                "residual": residual_sum,
                                "success": True
                            })

                except Exception as e:
                    # Ignore failed fits
                    print(f"Trial {trial + 1}/{num_trials} failed: {e}")


            if best_result["success"]:
                cell.a = best_result["a"]
                cell.b = best_result["a"]
                cell.c = best_result["c"]
                self.valid["unitCell"] = True
                return cell
            else:
                self.valid["unitCell"] = False
                print("All fits failed")

    def _buildCrystalStructure(self):
        # returns a mantid crystal structure
        
        # assert sufficient information to build a crystal structure
        if not all(self.valid.values()):
            print("Insufficient input to instantiate a CrystalStructure")
        else:
            #try to make CrystalStructure
            a = self.unitCell.a
            b = self.unitCell.b
            c = self.unitCell.c
            alpha = self.unitCell.alpha
            beta = self.unitCell.beta
            gamma = self.unitCell.gamma

            try: 
                self.crystalStructure = CrystalStructure(unitCell = f"{a} {b} {c} {alpha} {beta} {gamma}",
                    spaceGroup = self.spaceGroup,
                    scatterers=self.scatterers)
                return True
            except:
                print("Failed to generate crystalStructure object with provided input:")
                print(f"  unitCell: {a} {b} {c} {alpha} {beta} {gamma}")
                print(f"  spaceGroup: {self.spaceGroup}")
                print(f"  scatterers: {self.scatterers}")
                return False

    def printCrystal(self):
        a = self.unitCell.a
        b = self.unitCell.b
        c = self.unitCell.c
        alpha = self.unitCell.alpha
        beta = self.unitCell.beta
        gamma = self.unitCell.gamma
        print(f"unitCell: {a:.5f} {b:.5f} {c:.5f} {alpha:.1f} {beta:.1f} {gamma:.1f}")
        print(f"spaceGroup: {self.spaceGroup}")
        print(f"scatterers: {self.scatterers}")


    def _validateScatterers(self,scatterers):
        #TODO: properly validate provided mantid-type scatterer string. For now just crude check that 
        # the correct number of values are present

        element_symbols = [
            "H", "D", "He", "Li", "Be", "B",  "C",  "N",  "O",  "F",  "Ne",
            "Na", "Mg", "Al", "Si", "P",  "S",  "Cl", "Ar", "K",  "Ca",
            "Sc", "Ti", "V",  "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
            "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y",  "Zr",
            "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
            "Sb", "Te", "I",  "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
            "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
            "Lu", "Hf", "Ta", "W",  "Re", "Os", "Ir", "Pt", "Au", "Hg",
            "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
            "Pa", "U",  "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
            "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
            "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og"
        ]

        if scatterers == "":
            print("no scatterers specified")
            self.valid["scatterers"]=False
            self.scatterers = ""
            return

        atoms = scatterers.split(";")
        for atom in atoms:
            atom = atom.strip() #remove white space 
            # print(atom)
            params = atom.split(" ")
            
            problem = False
            if params[0].strip() not in element_symbols:
                raise ValueError(f"issue understanding atom type: {params[0]} (note, mantid crystal structure can\'t currently process isotopes)")
                problem = True #n.b. CrystalStructure doesn't handle isotopes still
            
            for param in params[1:4]:

                try: 
                    float(param)
                except:
                    raise ValueError("cannot convert string {param} to a float. Expecting an atomic coordinate")
                    problem = True

            
        if problem:
            raise ValueError("something went wrong trying to generate Mantid CrystalStructure check your input")
            self.valid["scatterers"]=False
            self.scatterers = ""
        else:
            self.valid["scatterers"]=True
            self.scatterers = scatterers
        return

    def calcDSpacings(self,dMin=0.5,dMax=10.0,minFractionOfMaxIntensity=0.8):
    
        #Generate reflections uses mantid crystal structure object and mantid tools to generate a corresponding list
        #of d-spacings. These can be filtered according to estimated intensity and minimum and maximum d-spacing

        if not self.hasCrystalStructure:
            print("object does not have a crystalStructure. Can\'t calculate d-spacings")
            return

        generator = ReflectionGenerator(self.crystalStructure)

        allRefs = generator.getUniqueHKLs(dMin,dMax)
        
        # Create list of unique reflections between 0.7 and 3.0 Angstrom
        hkls = generator.getUniqueHKLsUsingFilter(dMin, dMax, ReflectionConditionFilter.StructureFactor)
        # Calculate d and F^2
        dValues = generator.getDValues(hkls)
        fSquared = generator.getFsSquared(hkls)
        pointGroup = self.crystalStructure.getSpaceGroup().getPointGroup()
        
        # Make list of tuples and sort by d-values, descending, include point group for multiplicity.
        reflections = sorted([(hkl, d, fsq, len(pointGroup.getEquivalents(hkl))) for hkl, d, fsq in zip(hkls, dValues, fSquared)],
                                    key=lambda x: x[1] - x[0][0]*1e-6, reverse=True)
                                    
        
        print(f"before filtering have {len(reflections)} reflections")
        estInt = []
        for ref in reflections:
            # print(ref[0],ref[1],ref[2])
            estInt.append(ref[2]*ref[3]*ref[1]**4)
        
        
        maxInt = np.max(estInt)

        dFiltered = []
        for ref in reflections:
            
            estInt = ref[2]*ref[3]*ref[1]**4
            if estInt >= minFractionOfMaxIntensity*maxInt:
                
                dFiltered.append(ref[1])


        print(f"after filtering have {len(dFiltered)} reflections (this is {100*len(dFiltered)/len(reflections):.2f}%)")
        
        self.dSpacings = sorted(dFiltered,reverse=True)
        
        return

    def to_dict(self):
        """
        Converts the crystalSpecies object to a dictionary representation.
        """
        # Convert observedReflections to a list of dictionaries
        observed_reflections_dicts = [ref.to_dict() for ref in self.observedReflections]
    
        # Store unitCell attributes in a dictionary
        if self.unitCell:
            unit_cell_dict = {
                "crystalSystem": self.unitCell.crystalSystem,
                "a": self.unitCell.a,
                "b": self.unitCell.b,
                "c": self.unitCell.c,
                "alpha": self.unitCell.alpha,
                "beta": self.unitCell.beta,
                "gamma": self.unitCell.gamma
            }
        else:
            unit_cell_dict = None
    
        # Serialize the optional EquationOfState (a dataclass) if present.
        if self.eos is not None:
            try:
                from dataclasses import asdict as _asdict
                eos_dict = _asdict(self.eos)
            except Exception:
                eos_dict = None
        else:
            eos_dict = None

        # Create the dictionary representation
        species_dict = {
            "_schema_version": self.SCHEMA_VERSION,
            "name": self.name,
            "spaceGroup": self.spaceGroup,
            "observedReflections": observed_reflections_dicts,
            "scatterers": self.scatterers,
            "crystalSystem": self.crystalSystem,  # Add crystalSystem
            "valid": self.valid,
            "extentOverPosition": self.extentOverPosition,
            "unitCell": unit_cell_dict,
            "hasCrystalStructure": self.hasCrystalStructure,
            "dLimits": self.dLimits,  # <-- preserve dLimits
            "cifPath": self.cifPath,
            "role": self.role,
            "eos": eos_dict,
        }
    
        return species_dict
    
    @classmethod
    def from_dict(cls, d):
        """
        Creates a crystalSpecies object from a dictionary representation.
        """
        # Recreate crystalReflection objects from dictionaries
        observed_reflections_dicts = d.get("observedReflections", [])
        observed_reflections = [crystalReflection.from_dict(ref_dict) for ref_dict in observed_reflections_dicts]
    
        # Extract parameters from the dictionary
        space_group = d.get("spaceGroup", "")
        name = d.get("name")
        scatterers = d.get("scatterers", "")
        dLimits = d.get("dLimits", None)  # <-- restore dLimits
        cifPath = d.get("cifPath", None)
        role = d.get("role", "sample")

        # Reconstruct the optional EquationOfState dataclass.
        eos_dict = d.get("eos", None)
        eos = None
        if eos_dict:
            try:
                from snapwrap._inspectrum import EquationOfState
                eos = EquationOfState(**eos_dict)
            except Exception as exc:
                print(
                    f"WARNING: could not rehydrate EquationOfState from dict: {exc}"
                )
                eos = None

        # Create a crystalSpecies object
        species = cls(
            spaceGroup=space_group,
            observedReflections=observed_reflections,
            name=name,
            scatterers=scatterers,
            dLimits=dLimits,
            cifPath=cifPath,
            role=role,
            eos=eos,
        )

        # Track the on-disk schema version this dict came from (None == legacy).
        species._loaded_schema_version = d.get("_schema_version", None)
    
        # Restore additional attributes
        species.crystalSystem = d.get("crystalSystem")
        species.valid = d.get("valid")
        species.extentOverPosition = d.get("extentOverPosition")
        species.hasCrystalStructure = d.get("hasCrystalStructure")
    
        # Restore unitCell if present
        unit_cell_dict = d.get("unitCell")
        if unit_cell_dict:
            species.unitCell = unitCell(unit_cell_dict["crystalSystem"])
            species.unitCell.a = unit_cell_dict["a"]
            species.unitCell.b = unit_cell_dict["b"]
            species.unitCell.c = unit_cell_dict["c"]
            species.unitCell.alpha = unit_cell_dict["alpha"]
            species.unitCell.beta = unit_cell_dict["beta"]
            species.unitCell.gamma = unit_cell_dict["gamma"]
            species.valid["unitCell"] = True  # Mark unitCell as valid
    
        return species

    @classmethod
    def from_cif(cls, cifPath, name=None, dLimits=None, role="sample", eos=None):
        """Construct a ``crystalSpecies`` from a CIF file via Mantid's ``LoadCIF``.

        This mirrors the approach used by the standalone ``crystalBox.Box``
        class: a temporary sample workspace is created, ``LoadCIF`` parses the
        CIF and attaches a ``CrystalStructure`` to its sample, and we then
        extract the space group, unit-cell parameters and scatterer strings
        directly from that Mantid object.  This avoids re-implementing CIF
        parsing inside SNAPWrap and inherits whatever CIF dialects Mantid
        already supports.

        Args:
            cifPath: path to a CIF file on disk.
            name: optional human-readable name; defaults to the CIF stem.
            dLimits: optional ``(dMin, dMax)`` tuple, passed through to the
                ``crystalSpecies`` constructor.
            role: ``"sample"`` (default) or ``"calibrant"``.  See
                :attr:`crystalSpecies.ALLOWED_ROLES`.
            eos: optional ``EquationOfState`` instance to attach (used by the
                refinement bridge — see Phase B/D of the refinement plan).

        Returns:
            A fully-populated ``crystalSpecies`` whose ``unitCell`` reflects
            the CIF, with ``cifPath`` recorded for downstream provenance.
        """
        path = Path(cifPath)
        if not path.exists():
            raise FileNotFoundError(f"CIF file does not exist: {path}")

        ws_name = f"_snapwrap_cif_{path.stem}"
        CreateSampleWorkspace(OutputWorkspace=ws_name)
        try:
            LoadCIF(Workspace=ws_name, InputFile=str(path))
            mantid_cs = mtd[ws_name].sample().getCrystalStructure()

            spaceGroup = mantid_cs.getSpaceGroup().getHMSymbol()
            uc = mantid_cs.getUnitCell()
            scatterer_strs = _mantidScattererStrings(mantid_cs)
            scatterers = "; ".join(scatterer_strs)

            a, b, c = uc.a(), uc.b(), uc.c()
            alpha, beta, gamma = uc.alpha(), uc.beta(), uc.gamma()
        finally:
            if mtd.doesExist(ws_name):
                DeleteWorkspace(Workspace=ws_name)

        species = cls(
            spaceGroup=spaceGroup,
            observedReflections=[],
            name=name if name is not None else path.stem,
            scatterers=scatterers,
            dLimits=dLimits,
            cifPath=str(path),
            role=role,
            eos=eos,
        )

        # Populate unit-cell directly from CIF-derived Mantid values.
        species.unitCell = unitCell(species.crystalSystem)
        species.unitCell.a = a
        species.unitCell.b = b
        species.unitCell.c = c
        species.unitCell.alpha = alpha
        species.unitCell.beta = beta
        species.unitCell.gamma = gamma
        species.valid["unitCell"] = True

        species.hasCrystalStructure = species._buildCrystalStructure()
        return species

def speciesListToJson(species_list, runNumber):
    """
    Writes a list of crystalSpecies dictionaries to a JSON file.

    Args:
        species_list (list): A list of dictionaries, where each dictionary
                             represents a crystalSpecies object (created using
                             the to_dict() method).
        runNumner (int): run number is used to index the species to a specific data set
                             this is done by createing a file with an apprropiate name and path
    """

    ipts = GetIPTS(Instrument="SNAP", runNumber=runNumber)
    filePath = f"{ipts}shared/meta/sample/crystalSpecies{str(runNumber).zfill(6)}.json"

    try:
        with open(filePath, 'w') as f:
            json.dump(species_list, f, indent=4)  # Use indent for readability
        print(f"Successfully wrote species list to {filePath}")
    except Exception as e:
        print(f"Error writing species list to {filePath}: {e}")     

def speciesListFromJson(filePath):
    """
    Reads a list of crystalSpecies dictionaries from a JSON file and returns a list of crystalSpecies class instances.

    Args:
        filePath (str): The path to the JSON file to be read.

    Returns:
        list: A list of crystalSpecies class instances.
    """
    try:
        with open(filePath, 'r') as f:
            species_list_dicts = json.load(f)

        species_list = [crystalSpecies.from_dict(species_dict) for species_dict in species_list_dicts]
        print(f"Successfully read species list from {filePath}")
        return species_list

    except FileNotFoundError:
        print(f"Error: File not found at {filePath}")
        return []  # Return an empty list if the file doesn't exist
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {filePath}")
        return []  # Return an empty list if the JSON is invalid
    except Exception as e:
        print(f"Error reading species list from {filePath}: {e}")
        return []  # Return an empty list if any other error occurs