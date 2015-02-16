# encoding: utf-8
# cython: profile=False
# filename: qmc.pyx
'''

File: qmc.py
Author: Hadayat Seddiqi
Date: 10.13.14
Description: Do the path-integral quantum annealing.
             See: 10.1103/PhysRevB.66.094203

'''

cimport cython
import numpy as np
cimport numpy as np
cimport openmp
from cython.parallel import prange
from libc.math cimport exp as cexp
from libc.stdlib cimport rand as crand
from libc.stdlib cimport RAND_MAX as RAND_MAX
# from libc.stdio cimport printf as cprintf


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.embedsignature(True)
cpdef QuantumAnneal(np.float_t[:] sched,
                    int mcsteps,
                    int slices, 
                    float temp, 
                    int nspins, 
                    np.float_t[:, :] confs, 
                    np.float_t[:, :, :] nbs,
                    rng):
    """
    Execute quantum annealing part using path-integral quantum Monte Carlo.
    The Hamiltonian is:

    H = -\sum_k^P( \sum_ij J_ij s^k_i s^k_j + J_perp \sum_i s^k_i s^k+1_i )

    where J_perp = -PT/2 log(tanh(G/PT)). The second term on the RHS is a 
    1D Ising chain along the extra dimension. In other words, a spin in this
    Trotter slice is coupled to that same spin in the nearest-neighbor slices.

    The quantum annealing is controlled by the transverse field which starts
    at @transFieldStart and decreases by @transFieldStep for @annealingSteps
    number of steps. The ambient temperature is @annealingTemperature, and the
    total number of spins is @nSpins. @isingJ and @perpJ give the parts of the
    Hamiltonian to calculate the energies, and @configurations is a list of
    spin vectors of length @trotterSlices. @rng is the random number generator.

    Returns: None (spins are flipped in-place)
    """
    # Define some variables
    cdef int maxnb = nbs[0].shape[0]
    cdef int ifield = 0
    cdef float field = 0.0
    cdef float jperp = 0.0
    cdef int step = 0
    cdef int islice = 0
    cdef int sidx = 0
    cdef int tidx = 0
    cdef int si = 0
    cdef int spinidx = 0
    cdef float jval = 0.0
    cdef float ediff = 0.0
    cdef int tleft = 0
    cdef int tright = 0
    cdef np.ndarray[np.int_t, ndim=1] sidx_shuff = \
        rng.permutation(range(nspins))

    # Loop over transverse field annealing schedule
    for ifield in xrange(sched.size):
	# Calculate new coefficient for 1D Ising J
        jperp = -0.5*slices*temp*np.log(np.tanh(sched[ifield]/(slices*temp)))
        for step in xrange(mcsteps):
            # Loop over Trotter slices
            for islice in xrange(slices):
                # Loop over spins
                for sidx in sidx_shuff:
                    # loop through the neighbors
                    for si in xrange(maxnb):
                        # get the neighbor spin index
                        spinidx = int(nbs[sidx, si, 0])
                        # get the coupling value to that neighbor
                        jval = nbs[sidx, si, 1]
                        # self-connections are not quadratic
                        if spinidx == sidx:
                            ediff += -2.0*confs[sidx, islice]*jval
                        else:
                            ediff += -2.0*confs[sidx, islice]*(
                                jval*confs[spinidx, islice]
                            )
                    # periodic boundaries
                    if tidx == 0:
                        tleft = slices-1
                        tright = 1
                    elif tidx == slices-1:
                        tleft = slices-2
                        tright = 0
                    else:
                        tleft = islice-1
                        tright = islice+1
                    # now calculate between neighboring slices
                    ediff += -2.0*confs[sidx, islice]*(
                        jperp*confs[sidx, tleft])
                    ediff += -2.0*confs[sidx, islice]*(
                        jperp*confs[sidx, tright])
                    # Accept or reject
                    if ediff > 0.0:  # avoid overflow
                        confs[sidx, islice] *= -1
                    elif cexp(ediff/temp) > crand()/float(RAND_MAX):
                        confs[sidx, islice] *= -1
                # reset energy diff
                ediff = 0.0
            sidx_shuff = rng.permutation(sidx_shuff)

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.embedsignature(True)
cpdef QuantumAnneal_parallel(np.float_t[:] sched,
                             int mcsteps,
                             int slices, 
                             float temp, 
                             int nspins, 
                             np.float_t[:, :] confs, 
                             np.float_t[:, :, :] nbs,
                             int nthreads):
    """
    Execute quantum annealing part using path-integral quantum Monte Carlo.
    The Hamiltonian is:

    H = -\sum_k^P( \sum_ij J_ij s^k_i s^k_j + J_perp \sum_i s^k_i s^k+1_i )

    where J_perp = -PT/2 log(tanh(G/PT)). The second term on the RHS is a 
    1D Ising chain along the extra dimension. In other words, a spin in this
    Trotter slice is coupled to that same spin in the nearest-neighbor slices.

    The quantum annealing is controlled by the transverse field which starts
    at @transFieldStart and decreases by @transFieldStep for @annealingSteps
    number of steps. The ambient temperature is @annealingTemperature, and the
    total number of spins is @nSpins. @isingJ and @perpJ give the parts of the
    Hamiltonian to calculate the energies, and @configurations is a list of
    spin vectors of length @trotterSlices. @rng is the random number generator.

    This version attempts parallelization with OpenMP directives from Cython.

    Returns: None (spins are flipped in-place)
    """
    # Define some variables
    cdef int maxnb = nbs[0].shape[0]
    cdef int ifield = 0
    cdef float field = 0.0
    cdef float jperp = 0.0
    cdef int step = 0
    cdef int islice = 0
    cdef int sidx = 0
    cdef int tidx = 0
    cdef int si = 0
    cdef int spinidx = 0
    cdef float jval = 0.0
    cdef int tleft = 0
    cdef int tright = 0
    # only reason we don't use memoryview is because we need arr.fill()
    cdef np.ndarray[np.float_t, ndim=1] ediffs = np.zeros(nspins)

    # Loop over transverse field annealing schedule
    for ifield in xrange(sched.size):
	# Calculate new coefficient for 1D Ising J
        jperp = -0.5*slices*temp*np.log(np.tanh(sched[ifield]/(slices*temp)))
        for step in xrange(mcsteps):
            # Loop over Trotter slices
            for islice in xrange(slices):
                # Loop over spins
                for sidx in prange(nspins, nogil=True, 
                                   schedule='guided', 
                                   num_threads=nthreads):
                    # loop through the neighbors
                    for si in xrange(maxnb):
                        # get the neighbor spin index
                        spinidx = int(nbs[sidx, si, 0])
                        # get the coupling value to that neighbor
                        jval = nbs[sidx, si, 1]
                        # self-connections are not quadratic
                        if spinidx == sidx:
                            ediffs[sidx] += -2.0*confs[sidx, islice]*jval
                        else:
                            ediffs[sidx] += -2.0*confs[sidx, islice]*(
                                jval*confs[spinidx, islice]
                            )
                    # periodic boundaries
                    if tidx == 0:
                        tleft = slices-1
                        tright = 1
                    elif tidx == slices-1:
                        tleft = slices-2
                        tright = 0
                    else:
                        tleft = islice-1
                        tright = islice+1
                    # now calculate between neighboring slices
                    ediffs[sidx] += -2.0*confs[sidx, islice]*(
                        jperp*confs[sidx, tleft])
                    ediffs[sidx] += -2.0*confs[sidx, islice]*(
                        jperp*confs[sidx, tright])
                    # Accept or reject
                    if ediffs[sidx] > 0.0:  # avoid overflow
                        confs[sidx, islice] *= -1
                    elif cexp(ediffs[sidx]/temp) > crand()/float(RAND_MAX):
                        confs[sidx, islice] *= -1
                # reset
                ediffs.fill(0.0)