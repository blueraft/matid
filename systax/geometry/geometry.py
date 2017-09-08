"""This module defines functions for deriving geometry related quantities from
a atomic system.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import numpy as np

from ase.data import covalent_radii

from sklearn.cluster import DBSCAN


def get_moments_of_inertia(system, weight=True):
    """Calculates geometric inertia tensor, i.e., inertia tensor but with
    all masses are set to 1.

    I_ij = sum_k m_k (delta_ij * r_k^2 - x_ki * x_kj)
    with r_k^2 = x_k1^2 + x_k2^2 x_k3^2

    Args:
        system(ASE Atoms): Atomic system.

    Returns:
        (np.ndarray, np.ndarray): The eigenvalues and eigenvectors of the
        geometric inertia tensor.
    """
    # Move the origin to the geometric center
    positions = system.get_positions()
    centroid = get_center_of_mass(system, weight)
    pos_shifted = positions - centroid

    # Calculate the geometric inertia tensor
    if weight:
        weights = system.get_masses()
    else:
        weights = np.ones((len(system)))
    x = pos_shifted[:, 0]
    y = pos_shifted[:, 1]
    z = pos_shifted[:, 2]
    I11 = np.sum(weights*(y**2 + z**2))
    I22 = np.sum(weights*(x**2 + z**2))
    I33 = np.sum(weights*(x**2 + y**2))
    I12 = np.sum(-weights * x * y)
    I13 = np.sum(-weights * x * z)
    I23 = np.sum(-weights * y * z)

    I = np.array([
        [I11, I12, I13],
        [I12, I22, I23],
        [I13, I23, I33]])

    evals, evecs = np.linalg.eigh(I)

    return evals, evecs


def find_vacuum_directions(system, threshold=7.0):
    """Searches for vacuum gaps that are separating the periodic copies.

    TODO: Implement a n^2 search that allows the detection of more complex
    vacuum boundaries.

    Returns:
        np.ndarray: An array with a boolean for each lattice basis
        direction indicating if there is enough vacuum to separate the
        copies in that direction.
    """
    rel_pos = system.get_scaled_positions()
    pbc = system.get_pbc()

    # Find the maximum vacuum gap for all basis vectors
    gaps = np.empty(3, dtype=bool)
    for axis in range(3):
        if not pbc[axis]:
            gaps[axis] = True
            continue
        comp = rel_pos[:, axis]
        ind = np.sort(comp)
        ind_rolled = np.roll(ind, 1, axis=0)
        distances = ind - ind_rolled

        # The first distance is from first to last, so it needs to be
        # wrapped around
        distances[0] += 1

        # Find maximum gap in cartesian coordinates
        max_gap = np.max(distances)
        basis = system.get_cell()[axis, :]
        max_gap_cartesian = np.linalg.norm(max_gap*basis)
        has_vacuum_gap = max_gap_cartesian >= threshold
        gaps[axis] = has_vacuum_gap

    return gaps


def get_center_of_mass(system, weight=True):
    """
    """
    positions = system.get_positions()
    if weight:
        weights = system.get_masses()
    else:
        weights = np.ones((len(system)))
    cm = np.dot(weights, positions/weights.sum())

    return cm


def get_extended_system(system, target_size):
    """Replicate the system in different directions to reach a suitable
    system size for getting the moments of inertia.

    Args:
        system (ase.Atoms): The original system.
        target_size (float): The target size for the extended system.

    Returns:
        ase.Atoms: The extended system.
    """
    pbc = system.get_pbc()
    cell = system.get_cell()

    repetitions = np.array([1, 1, 1])
    for i, pbc in enumerate(pbc):
        # Only extend in the periodic dimensions
        basis = cell[i, :]
        if pbc:
            size = np.linalg.norm(basis)
            i_repetition = np.maximum(np.round(target_size/size), 1).astype(int)
            repetitions[i] = i_repetition

    extended_system = system.repeat(repetitions)

    return extended_system


def get_clusters(system):
    """
    """
    if len(system) == 1:
        return np.array([[0]])

    # Calculate distance matrix with radii taken into account
    distance_matrix = system.get_all_distances(mic=True)

    # Remove the radii from distances
    for i, i_number in enumerate(system.get_atomic_numbers()):
        for j, j_number in enumerate(system.get_atomic_numbers()):
            i_radii = covalent_radii[i_number]
            j_radii = covalent_radii[j_number]
            new_value = distance_matrix[i, j] - i_radii - j_radii
            distance_matrix[i, j] = max(new_value, 0)

    # Detect clusters
    db = DBSCAN(eps=1.35, min_samples=1, metric='precomputed', n_jobs=-1)
    db.fit(distance_matrix)
    clusters = db.labels_

    # Make a list of the different clusters
    idx_sort = np.argsort(clusters)
    sorted_records_array = clusters[idx_sort]
    vals, idx_start, count = np.unique(sorted_records_array, return_counts=True,
                                    return_index=True)
    cluster_indices = np.split(idx_sort, idx_start[1:])

    return cluster_indices


def get_biggest_gap_indices(coordinates):
    """Given the list of coordinates for one axis, this function will find the
    maximum gap between them and return the index of the bottom and top
    coordinates. The bottom and top are defined as:

    ===       ===============    --->
        ^top    ^bot               ^axis direction
    """
    # Find the maximum vacuum gap for all basis vectors
    sorted_indices = np.argsort(coordinates)
    sorted_comp = coordinates[sorted_indices]
    rolled_comp = np.roll(sorted_comp, 1, axis=0)
    distances = sorted_comp - rolled_comp

    # The first distance is from first to last, so it needs to be
    # wrapped around
    distances[0] += 1

    # Find maximum gap
    bottom_index = sorted_indices[np.argmax(distances)]
    top_index = sorted_indices[np.argmax(distances)-1]

    return bottom_index, top_index


def get_dimensions(system, vacuum_gaps):
    """Given a system with vacuum gaps, calculate its dimensions in the
    directions with vacuum gaps by also taking into account the atomic radii.
    """
    orig_cell_lengths = np.linalg.norm(system.get_cell(), axis=1)

    # Create a repeated copy of the system. The repetition is needed in order
    # to get gaps to neighbouring cell copies in the periodic dimensions with a
    # vacuum gap
    sys = system.copy()
    sys = sys.repeat([2, 2, 2])

    dimensions = [None, None, None]
    numbers = sys.get_atomic_numbers()
    positions = sys.get_scaled_positions()
    radii = covalent_radii[numbers]
    cell_lengths = np.linalg.norm(sys.get_cell(), axis=1)
    radii_in_cell_basis = radii[:, None]/cell_lengths[None, :]

    for i_dim, vacuum_gap in enumerate(vacuum_gaps):
        if vacuum_gap:
            # Make a data structure containing the atom location information as
            # intervals from one side of the atom to the other in each
            # dimension.
            intervals = Intervals()
            for i_pos, pos in enumerate(positions[:, i_dim]):
                i_radii = radii_in_cell_basis[i_pos, i_dim]
                i_axis_start = pos - i_radii
                i_axis_end = pos + i_radii
                intervals.add_interval(i_axis_start, i_axis_end)

            # Calculate the maximum distance between atoms, when taking radius
            # into account
            gap = intervals.get_max_distance_between_intervals()
            gap = gap*cell_lengths[i_dim]
            dimensions[i_dim] = orig_cell_lengths[i_dim] - gap

    return dimensions


def get_wrapped_positions(scaled_pos, precision=1E-5):
    """Wrap the given relative positions so that each element in the array
    is within the half-closed interval [0, 1)

    By wrapping values near 1 to 0 we will have a consistent way of
    presenting systems.
    """
    scaled_pos %= 1

    abs_zero = np.absolute(scaled_pos)
    abs_unity = np.absolute(abs_zero-1)

    near_zero = np.where(abs_zero < precision)
    near_unity = np.where(abs_unity < precision)

    scaled_pos[near_unity] = 0
    scaled_pos[near_zero] = 0

    return scaled_pos


# def get_displacement_tensor(self, system):
    # """A matrix where the entry A[i, j, :] is the vector
    # self.cartesian_pos[i] - self.cartesian_pos[j].

    # For periodic systems the distance of an atom from itself is the
    # smallest displacement of an atom from one of it's periodic copies, and
    # the distance of two different atoms is the distance of two closest
    # copies.

    # Returns:
        # np.array: 3D matrix containing the pairwise distance vectors.
    # """
    # if self.pbc.any():
        # pos = self.get_scaled_positions()
        # disp_tensor = pos[:, None, :] - pos[None, :, :]

        # # Take periodicity into account by wrapping coordinate elements
        # # that are bigger than 0.5 or smaller than -0.5
        # indices = np.where(disp_tensor > 0.5)
        # disp_tensor[indices] = 1 - disp_tensor[indices]
        # indices = np.where(disp_tensor < -0.5)
        # disp_tensor[indices] = disp_tensor[indices] + 1

        # # Transform to cartesian
        # disp_tensor = self.to_cartesian(disp_tensor)

        # # Figure out the smallest basis vector and set it as
        # # displacement for diagonal
        # cell = self.get_cell()
        # basis_lengths = np.linalg.norm(cell, axis=1)
        # min_index = np.argmin(basis_lengths)
        # min_basis = cell[min_index]
        # diag_indices = np.diag_indices(len(disp_tensor))
        # disp_tensor[diag_indices] = min_basis

    # else:
        # pos = self.get_positions()
        # disp_tensor = pos[:, None, :] - pos[None, :, :]

    # return disp_tensor


# def get_distance_matrix(self, system):
    # """Calculates the distance matrix A defined as:

        # A_ij = |r_i - r_j|

    # For periodic systems the distance of an atom from itself is the
    # smallest displacement of an atom from one of it's periodic copies, and
    # the distance of two different atoms is the distance of two closest
    # copies.

    # Returns:
        # np.array: Symmetric 2D matrix containing the pairwise distances.
    # """
    # displacement_tensor = self.get_displacement_tensor(system)
    # distance_matrix = np.linalg.norm(displacement_tensor, axis=2)
    # return distance_matrix


class Intervals(object):
    """Handles list of intervals.

    This class allows sorting and adding up of intervals and taking into
    account if they overlap.
    """
    def __init__(self, intervals=None):
        """Args:
            intervals: List of intervals that are added.
        """
        self._intervals = []
        self._merged_intervals = []
        self._merged_intervals_need_update = True
        if intervals is not None:
            self.add_intervals(intervals)

    def _add_up(self, intervals):
        """Add up the length of intervals.

        Argument:
            intervals: List of intervals that are added up.

        Returns:
            Result of addition.
        """
        if len(intervals) < 1:
            return None
        result = 0.
        for interval in intervals:
            result += abs(interval[1] - interval[0])
        return result

    def add_interval(self, a, b):
        """Add one interval.

        Args:
            a, b: Start and end of interval. The order does not matter.
        """
        self._intervals.append((min(a, b), max(a, b)))
        self._merged_intervals_need_update = True

    def add_intervals(self, intervals):
        """Add list of intervals.

        Args:
            intervals: List of intervals that are added.
        """
        for interval in intervals:
            if len(interval) == 2:
                self.add_interval(interval[0], interval[1])
            else:
                raise ValueError("Intervals must be tuples of length 2!")

    def set_intervals(self, intervals):
        """Set list of intervals.

        Args:
            intervals: List of intervals that are set.
        """
        self._intervals = []
        self.add_intervals(intervals)

    def remove_interval(self, i):
        """Remove one interval.

        Args:
            i: Index of interval that is removed.
        """
        try:
            del self._intervals[i]
            self._merged_intervals_need_update = True
        except IndexError:
            pass

    def get_intervals(self):
        """Returns the intervals.
        """
        return self._intervals

    def get_intervals_sorted_by_start(self):
        """Returns list with intervals ordered by their start.
        """
        return sorted(self._intervals, key=lambda x: x[0])

    def get_intervals_sorted_by_end(self):
        """Returns list with intervals ordered by their end.
        """
        return sorted(self._intervals, key=lambda x: x[1])

    def get_merged_intervals(self):
        """Returns list of merged intervals so that they do not overlap anymore.
        """
        if self._merged_intervals_need_update:
            if len(self._intervals) < 1:
                return self._intervals
            # sort intervals in list by their start
            sorted_by_start = self.get_intervals_sorted_by_start()
            # add first interval
            merged = [sorted_by_start[0]]
            # start from second interval
            for current in sorted_by_start[1:]:
                previous = merged[-1]
                # new interval if not current and previous are not overlapping
                if previous[1] < current[0]:
                    merged.append(current)
                # merge if current and previous are overlapping and if end of previous is expanded by end of current
                elif previous[1] < current[1]:
                    merged[-1] = (previous[0], current[1])
            self._merged_intervals = merged
            self._merged_intervals_need_update = False
        return self._merged_intervals

    def get_max_distance_between_intervals(self):
        """Returns the maximum distance between the intervals while accounting for overlap.
        """
        if len(self._intervals) < 2:
            return None
        merged_intervals = self.get_merged_intervals()
        distances = []
        if len(merged_intervals) == 1:
            return 0.0
        for i in range(len(merged_intervals) - 1):
            distances.append(abs(merged_intervals[i + 1][0] - merged_intervals[i][1]))
        return max(distances)

    def add_up_intervals(self):
        """Returns the added up lengths of intervals without accounting for overlap.
        """
        return self._add_up(self._intervals)

    def add_up_merged_intervals(self):
        """Returns the added up lengths of merged intervals in order to account for overlap.
        """
        return self._add_up(self.get_merged_intervals())
