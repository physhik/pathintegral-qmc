'''

File: piqa.py
Author: Hadayat Seddiqi
Date: 10.07.14
Description: Do path-integral quantum annealing, i.e., run a quantum 
             annealing simulation using path-integral quantum Monte 
             Carlo. See: 10.1103/PhysRevB.66.094203

'''

import argparse
import numpy as np
import scipy.sparse as sps

import gen_ising
# C extensions
import pyximport; pyximport.install()
import sa
import qmc


def bits2spins(vec):
    """ Convert a bitvector @vec to a spinvector. """
    return [ 1 if k == 1 else -1 for k in vec ]

def spins2bits(vec):
    """ Convert a spinvector @vec to a bitvector. """
    return [ 0 if k == 1 else 1 for k in vec ]

def GenerateNeighbors(nspins, J):
    """
    Precompute a list that include neighboring indices to each spin
    and the corresponding coupling value. Specifically, build:

    neighbors = [ [ (ni_0, J[0, ni_0]), (ni_1, J[0, ni_1]), ... ],
                  [ (ni_0, J[1, ni_0]), (ni_1, J[1, ni_1]), ... ],
                  ...
                  [ (ni_0, J[nspins-1, ni_0]), ... ] ]

    Inputs:  @npsins   number of spins in the 2D lattice
             @J        Ising coupling matrix

    Returns: the above specified "neighbors" list as a numpy array.
    """
    # Precompute neighbors for each spin
    nrows = int(np.sqrt(nspins))
    J = J.todok()  # dictionary of keys type makes this easy
    neighbors = []
    # Iterate over all spins
    for ispin in xrange(nspins):
        nb_pairs = []
        # Find the pairs including this spin
        for pair in J.iterkeys():
            if pair[0] == ispin:
                nb_pairs.append([ pair[1], J[pair] ])
            elif pair[1] == ispin:
                nb_pairs.append([ pair[0], J[pair] ])
        # Record it in the master list
        neighbors.append(nb_pairs)
    J = J.todia()  # DOK is really slow for multiplication
    return neighbors


def SimulateQuantumAnnealing(trotterSlices, nSpins, annealingTemperature,
                             annealingSteps, transFieldStart, transFieldEnd,
                             preAnnealing, preAnnealingSteps, 
                             preAnnealingTemperature, randomSeed, inputfname,
                             verbose):
    """
    Simulate quantum annealing using a path-integral quantum Monte Carlo
    scheme. Inputs are described in the help strings for parsing the cmdargs
    in the main section. The actual method is as follows:

    1. Initialize a random binary spin vector
    2. Do classical annealing to find a decent starting configuration
    3. Copy this over all Trotter slices and do quantum Monte Carlo
    4. Find the Trotter slice with the lowest energy configuration

    Returns: [ ground state energy, spin configuration ]
             [ float, np.array ]
    """
    # Random number generator
    seed = 1234 if randomSeed else None
    rng = np.random.RandomState(seed)
    # Initialize matrix
    isingJ = 0
    # Warn if it's not square
    if np.sqrt(nSpins) != np.abs(np.sqrt(nSpins)):
        print("Warning: number of spins indicates non-square lattice.")
    # Construct it, somehow
    if inputfname is None:
        # Get a randomly generated problem in sparse diagonal format
        isingJ = gen_ising.Generate2DIsing(np.sqrt(nSpins), rng).todia()
    else:
        # Read in the diagonals of the 2D Ising instance
        loader = np.load(inputfname)
        nSpins = loader['nSpins'][0]
        # Reconstruct the matrix in sparse diagonal format
        isingJ = sps.dia_matrix(([loader['hcons'], loader['vcons'],
                                  loader['phcons'], loader['pvcons']],
                                 loader['k']),
                                shape=(nSpins, nSpins))

    #
    # Pre-annealing stage:
    #
    # Start with an initial random configuration at @initTemperature 
    # and perform classical annealing down to @temperature to obtain 
    # the initial configuration across all Trotter slices for QMC.
    #

    # Random initial configuration of spins
    spinVector = np.array([ 2*rng.randint(2)-1 for k in range(nSpins) ], 
                          dtype=np.float)

    # Generate list of nearest-neighbors for each spin
    neighbors = GenerateNeighbors(nSpins, isingJ)

    if verbose:
        print ("Initial energy: ", sa.ClassicalIsingEnergy(spinVector, isingJ))

    # Do the pre-annealing
    if preAnnealing:
        sa.Anneal(preAnnealingTemperature, annealingTemperature,
                  preAnnealingSteps, spinVector, neighbors, rng)

    if verbose:
        print ("Final pre-annealing energy: ", 
               sa.ClassicalIsingEnergy(spinVector, isingJ))

    #
    # Quantum Monte Carlo:
    #
    # Copy pre-annealed configuration as the initial configuration for all
    # Trotter slices and carry out the true quantum annealing dynamics.
    #

    # Copy spin system over all the Trotter slices
    # Rows are spin indices, columns represent Trotter slices
    configurations = np.tile(spinVector, (trotterSlices, 1)).T

    # Calculate number of steps to decrease transverse field
    transFieldStep = ((transFieldStart-transFieldEnd)/annealingSteps)

    # Execute quantum annealing part
    qmc.QuantumAnneal(transFieldStart, transFieldStep, annealingSteps, 
                      trotterSlices, annealingTemperature, nSpins,
                      configurations, neighbors, rng)

    # Get the lowest energy and configuration
    minEnergy, minConfiguration = np.inf, []
    for col in configurations.T:
        candidateEnergy = sa.ClassicalIsingEnergy(col, isingJ)
        if candidateEnergy < minEnergy:
            minEnergy = candidateEnergy
            minConfiguration = col

    if verbose:
        energies = [ sa.ClassicalIsingEnergy(c, isingJ) 
                     for c in configurations.T ]
        print "Final quantum annealing energy: "
        print "Lowest: ", np.min(energies)
        print "Highest: ", np.max(energies)
        print "Average: ", np.average(energies)
        print "All: "
        print energies

    return minEnergy, minConfiguration


if __name__ == "__main__":
    # Get some command line args
    parser = argparse.ArgumentParser()
    parser.add_argument("--nspins", 
                        default=8,
                        nargs='?',
                        type=int,
                        help="Number of spins in 2D Ising lattice.")
    parser.add_argument("--trotterslices", 
                        default=20,
                        nargs='?',
                        type=int,
                        help="Number of Trotter slices.")
    parser.add_argument("--temperature", 
                        default=0.01,
                        nargs='?',
                        type=float,
                        help="Temperature during quantum annealing.")
    parser.add_argument("--annealingsteps", 
                        default=100,
                        nargs='?',
                        type=int,
                        help="Number of steps in the quantum annealing.")
    parser.add_argument("--transfieldstart", 
                        default=1.5,
                        nargs='?',
                        type=float,
                        help="Starting magnetic field for the QMC.")
    parser.add_argument("--transfieldend", 
                        default=1e-8,
                        nargs='?',
                        type=float,
                        help="Final magnetic field for the QMC.")
    parser.add_argument("--preannealing", 
                        default=1,
                        nargs='?',
                        type=int,
                        help="Do classical preannealing starting from random "+\
                            "state (1) or start QMC from random state (0).")
    parser.add_argument("--preannealingsteps", 
                        default=1,
                        nargs='?',
                        type=int,
                        help="Number of Monte Carlo steps on each spin.")
    parser.add_argument("--preannealingtemperature", 
                        default=3.0,
                        nargs='?',
                        type=float,
                        help="Starting temperature for the preannealing.")
    parser.add_argument("--randomseed", 
                        default=0,
                        nargs='?',
                        type=int,
                        help="Seed random number generator (1) or not (0).")
    parser.add_argument("--inputfname", 
                        default=None,
                        nargs='?',
                        type=str,
                        help="Name of the input file for the Ising matrix.")
    parser.add_argument("--verbose", 
                        default=0,
                        nargs='?',
                        type=int,
                        help="Print out some extra stuff (0: False, 1: True).")
    # Parse the inputs
    args = parser.parse_args()
    # Assign these variables
    trotterSlices = args.trotterslices
    nSpins = args.nspins
    annealingTemperature = args.temperature
    annealingSteps = args.annealingsteps
    transFieldStart = args.transfieldstart
    transFieldEnd = args.transfieldend
    preAnnealing = args.preannealing
    preAnnealingSteps = args.preannealingsteps
    preAnnealingTemperature = args.preannealingtemperature
    randomSeed = args.randomseed
    inputfname = args.inputfname
    verbose = args.verbose

    # Execute quantum annealing simulation
    e, c = SimulateQuantumAnnealing(trotterSlices, nSpins, 
                                    annealingTemperature,
                                    annealingSteps, transFieldStart, 
                                    transFieldEnd, preAnnealing, 
                                    preAnnealingSteps, preAnnealingTemperature,
                                    randomSeed, inputfname, verbose=1)
