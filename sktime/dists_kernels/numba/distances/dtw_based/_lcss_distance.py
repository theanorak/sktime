# -*- coding: utf-8 -*-
from typing import Callable, Union

import numpy as np
from numba import njit

from sktime.dists_kernels.numba.distances._numba_utils import _compute_pairwise_distance
from sktime.dists_kernels.numba.distances._squared_distance import _SquaredDistance
from sktime.dists_kernels.numba.distances.base import DistanceCallable, NumbaDistance
from sktime.dists_kernels.numba.distances.dtw_based.lower_bounding import (
    LowerBounding,
    resolve_bounding_matrix,
)


class _LcssDistance(NumbaDistance):
    """Longest common subsequence (Lcss) between two timeseries."""

    def _distance_factory(
        self,
        x: np.ndarray,
        y: np.ndarray,
        lower_bounding: Union[LowerBounding, int] = LowerBounding.NO_BOUNDING,
        window: int = 2,
        itakura_max_slope: float = 2.0,
        custom_distance: DistanceCallable = _SquaredDistance().distance_factory,
        bounding_matrix: np.ndarray = None,
        epsilon: float = 1.0,
        **kwargs: dict,
    ) -> DistanceCallable:
        """Create a no_python compiled lcss distance callable.

        Parameters
        ----------
        x: np.ndarray (2d array)
            First timeseries.
        y: np.ndarray (2d array)
            Second timeseries.
        lower_bounding: LowerBounding or int, defaults = LowerBounding.NO_BOUNDING
            Lower bounding technique to use.
        window: int, defaults = 2
            Integer that is the radius of the sakoe chiba window (if using Sakoe-Chiba
            lower bounding).
        itakura_max_slope: float, defaults = 2.
            Gradient of the slope for itakura parallelogram (if using Itakura
            Parallelogram lower bounding).
        custom_distance: Callable[[np.ndarray, np.ndarray], float],
                        defaults = squared_distance
            Distance function to used to compute distance between timeseries.
        bounding_matrix: np.ndarray (2d of size mxn where m is len(x) and n is len(y))
            Custom bounding matrix to use. If defined then other lower_bounding params
            and creation are ignored. The matrix should be structure so that indexes
            considered in bound should be the value 0. and indexes outside the bounding
            matrix should be infinity.
        epsilon : float, defaults = 1.
            Matching threshold to determine if two subsequences are considered close
            enough to be considered 'common'.
        kwargs: dict
            Extra arguments for custom distance should be put in the kwargs. See the
            documentation for the distance for kwargs.

        Returns
        -------
        Callable[[np.ndarray, np.ndarray], float]
            No_python compiled lcss distance callable.

        Raises
        ------
        ValueError
            If the input timeseries is not a numpy array.
            If the input timeseries doesn't have exactly 2 dimensions.
            If the sakoe_chiba_window_radius is not an integer.
            If the itakura_max_slope is not a float or int.
        """
        _bounding_matrix = resolve_bounding_matrix(
            x, y, lower_bounding, window, itakura_max_slope, bounding_matrix
        )

        # This needs to be here as potential distances only known at runtime not
        # compile time so having this at the top would cause circular import errors.
        from sktime.dists_kernels.numba.distances.distance import distance_factory

        _custom_distance = distance_factory(x, y, metric=custom_distance, **kwargs)

        @njit()
        def numba_wdtw_distance(
            _x: np.ndarray,
            _y: np.ndarray,
        ) -> float:
            return _numba_lcss_distance(
                _x, _y, _custom_distance, _bounding_matrix, epsilon
            )

        return numba_wdtw_distance


@njit(cache=True)
def _numba_lcss_distance(
    x: np.ndarray,
    y: np.ndarray,
    distance: Callable[[np.ndarray, np.ndarray], float],
    bounding_matrix: np.ndarray,
    epsilon: float,
) -> float:
    """Lcss distance compiled to no_python.

    Parameters
    ----------
    x: np.ndarray (2d array)
        First timeseries.
    y: np.ndarray (2d array)
        Second timeseries.
    distance: Callable[[np.ndarray, np.ndarray], float],
                    defaults = squared_distance
        Distance function to used to compute distance between timeseries.
    bounding_matrix: np.ndarray (2d of size mxn where m is len(x) and n is len(y))
        Bounding matrix where the values in bound are marked by finite values and
        outside bound points are infinite values.
    epsilon : float
        Matching threshold to determine if two subsequences are considered close enough
        to be considered 'common'.

    Returns
    -------
    float
        lcss between two timeseries.
    """
    symmetric = np.array_equal(x, y)
    pre_computed_distances = _compute_pairwise_distance(x, y, symmetric, distance)

    cost_matrix = _sequence_cost_matrix(
        x, y, bounding_matrix, pre_computed_distances, epsilon
    )
    return float(cost_matrix[-1, -1] / min(x.shape[0], y.shape[0]))


@njit(cache=True)
def _sequence_cost_matrix(
    x: np.ndarray,
    y: np.ndarray,
    bounding_matrix: np.ndarray,
    pre_computed_distances: np.ndarray,
    epsilon: float,
):
    """Compute the lcss cost matrix between two timeseries.

    Parameters
    ----------
    x: np.ndarray (2d array)
        First timeseries.
    y: np.ndarray (2d array)
        Second timeseries.
    bounding_matrix: np.ndarray (2d of size mxn where m is len(x) and n is len(y))
        Bounding matrix where the values in bound are marked by finite values and
        outside bound points are infinite values.
    pre_computed_distances: np.ndarray (2d of size mxn where m is len(x) and n is
                                        len(y))
        Pre-computed distances.
    epsilon : float
        Matching threshold to determine if two subsequences are considered close enough
        to be considered 'common'.

    Returns
    -------
    np.ndarray
        Lcss cost matrix between x and y.
    """
    x_size = x.shape[0]
    y_size = y.shape[0]
    cost_matrix = np.zeros((x_size + 1, y_size + 1))

    for i in range(1, x_size + 1):
        for j in range(1, y_size + 1):
            if np.isfinite(bounding_matrix[i - 1, j - 1]):
                if pre_computed_distances[i - 1, j - 1] <= epsilon:
                    cost_matrix[i, j] = 1 + cost_matrix[i - 1, j - 1]
                else:
                    cost_matrix[i, j] = max(
                        cost_matrix[i, j - 1], cost_matrix[i - 1, j]
                    )

    return cost_matrix
