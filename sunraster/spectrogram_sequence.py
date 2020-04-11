import textwrap
import numbers

import numpy as np
import astropy.units as u
import ndcube.utils.sequence
from ndcube import NDCubeSequence

from sunraster.spectrogram import SpectrogramABC
from sunraster import utils

__all__ = ['SpectrogramSequence', 'RasterSequence']

RASTER_AXIS_NAME = "raster scan"
SNS_AXIS_NAME = "temporal"
SLIT_STEP_AXIS_NAME = "slit step"
SLIT_AXIS_NAME = "position along slit"
SPECTRAL_AXIS_NAME = "spectral"


class SpectrogramSequence(NDCubeSequence, SpectrogramABC):
    """
    Class for holding, slicing and plotting a sequence of spectrogram cubes.

    Spectrogram cubes can be 2D or higher.

    Parameters
    ----------
    data_list: `list`
        List of `SpectrogramCube` objects from the same spectral window and OBS ID.
        Must also contain the 'detector type' in its meta attribute.

    common_axis: `int` or `None` (optional)
        If the sequence axis is aligned with an axis of the component SpectrogramCube
        instances, e.g. Spectrogram cubes have a time dimension and are arranged within
        the sequence in chronological order, set this input to the axis number of the
        time axis within the cubes.
        Default=None implies there is no common axis.

    meta: `dict` or header object (optional)
        Metadata associated with the sequence.
    """
    def __init__(self, data_list, common_axis=None, meta=None):
        # Initialize Sequence.
        super().__init__(data_list, common_axis=common_axis, meta=meta)

    @property
    def spectral_axis(self):
        return u.Quantity([raster.spectral_axis for raster in self.data])

    @property
    def time(self):
        return np.concatenate([raster.time for raster in self.data])

    @property
    def exposure_time(self):
        return np.concatenate([raster.exposure_time for raster in self.data])

    @property
    def lon(self):
        return u.Quantity([raster.lon for raster in self.data])

    @property
    def lat(self):
        return u.Quantity([raster.lat for raster in self.data])

    def apply_exposure_time_correction(self, undo=False, copy=False, force=False):
        """
        Applies or undoes exposure time correction to data and uncertainty and
        adjusts unit.

        Correction is only applied (undone) if the object's unit doesn't (does)
        already include inverse time.  This can be overridden so that correction
        is applied (undone) regardless of unit by setting force=True.

        Parameters
        ----------
        undo: `bool`
            If False, exposure time correction is applied.
            If True, exposure time correction is removed.
            Default=False

        copy: `bool`
            If True a new instance with the converted data values is returned.
            If False, the current instance is overwritten.
            Default=False

        force: `bool`
            If not True, applies (undoes) exposure time correction only if unit
            doesn't (does) already include inverse time.
            If True, correction is applied (undone) regardless of unit.  Unit is still
            adjusted accordingly.

        Returns
        -------
        result: `None` or `SpectrogramSequence`
            If copy=False, the original SpectrogramSequence is modified with the
            exposure time correction applied (undone).
            If copy=True, a new SpectrogramSequence is returned with the correction
            applied (undone).
        """
        converted_data_list = []
        for cube in self.data:
            converted_data_list.append(cube.apply_exposure_time_correction(undo=undo,
                                                                           force=force))
        if copy is True:
            return self.__class__(
                converted_data_list, meta=self.meta, common_axis=self._common_axis)
        else:
            self.data = converted_data_list

    def __str__(self):
        data0 = self.data[0]
        if data0._time_name:
            start_time = data0.time.value if data0.time.isscalar else data0.time[0].value
            data_1 = self.data[-1]
            stop_time = data_1.time.value if data_1.time.isscalar  else data_1.time[-1].value
            time_period = start_time if start_time == stop_time else (start_time, stop_time)
        else:
            time_period = None
        if data0._longitude_name:
            lons = self.lon
            lon_min = lons.min()
            lon_max = lons.max()
            lon_range = lon_min if lon_min == lon_max else u.Quantity([lon_min, lon_max])
        else:
            lon_range = None
        if data0._latitude_name:
            lats = self.lat
            lat_min = lats.min()
            lat_max = lats.max()
            lat_range = lat_min if lat_min == lat_max else u.Quantity([lat_min, lat_max])
        else:
            lat_range = None
        if data0._spectral_name:
            spectral_vals = self.spectral_axis
            spectral_min = spectral_vals.min()
            spectral_max = spectral_vals.max()
            spectral_range = spectral_min if spectral_min == spectral_max else \
                u.Quantity([spectral_min, spectral_max])
        else:
            spectral_range = None
        return (textwrap.dedent(f"""\
                {self.__class__.__name__}
                {"".join(["-"] * len(self.__class__.__name__))}
                Time Range: {time_period}
                Pixel Dimensions: {self.dimensions}
                Longitude range: {lon_range}
                Latitude range: {lat_range}
                Spectral range: {spectral_range}
                Data unit: {self.data[0].unit}"""))

    def __repr__(self):
        return f"{object.__repr__(self)}\n{str(self)}"


class RasterSequence(SpectrogramSequence):
    """
    Class for holding, slicing and plotting series of spectrograph raster scans.

    Parameters
    ----------
    data_list: `list`
        List of `SpectrogramCube` objects from the same spectral window and OBS ID.
        Must also contain the 'detector type' in its meta attribute.

    common_axis: `int`
        The axis of the SpectrogramCube instances corresponding to the slit step axis.

    meta: `dict` or header object (optional)
        Metadata associated with the sequence.
    """
    def __init__(self, data_list, common_axis, meta=None):
        # Initialize Sequence.
        super().__init__(data_list, common_axis=common_axis, meta=meta)

        # Determine axis indices of instrument axis types.
        self._raster_axis_name = RASTER_AXIS_NAME
        self._SnS_axis_name = SNS_AXIS_NAME
        self._slit_step_axis_name = SLIT_STEP_AXIS_NAME
        self._slit_axis_name = SLIT_AXIS_NAME
        self._spectral_axis_name = SPECTRAL_AXIS_NAME
        self._single_scan_instrument_axes_types = np.empty(self.data[0].data.ndim, dtype=object)
        # Slit step axis name.
        if self._common_axis is not None:
            self._single_scan_instrument_axes_types[self._common_axis] = self._slit_step_axis_name
        # Spectral axis name.
        spectral_raster_index = np.where(np.array(self.data[0].world_axis_physical_types) ==
                                         self.data[0]._spectral_name)
        if len(spectral_raster_index) == 1:
            self._single_scan_instrument_axes_types[spectral_raster_index] = \
                    self._spectral_axis_name
        # Slit axis name.
        w = self._single_scan_instrument_axes_types == None
        if w.sum() > 1:
            raise ValueError("WCS, missing_axes, and/or common_axis not consistent.")
        self._single_scan_instrument_axes_types[w] = self._slit_axis_name
        # Remove any instrument axes types whose axes are missing.
        self._single_scan_instrument_axes_types.astype(str)

    raster_dimensions = SpectrogramSequence.dimensions
    SnS_dimensions = SpectrogramSequence.cube_like_dimensions
    raster_world_axis_physical_types = SpectrogramSequence.world_axis_physical_types
    SnS_world_axis_physical_types = SpectrogramSequence.cube_like_world_axis_physical_types
    raster_axis_extra_coords = SpectrogramSequence.sequence_axis_extra_coords
    SnS_axis_extra_coords = SpectrogramSequence.common_axis_extra_coords
    plot_as_raster = SpectrogramSequence.plot
    plot_as_SnS = SpectrogramSequence.plot_as_cube

    @property
    def slice_as_SnS(self):
        """
        Method to slice instance as though data were taken as a sit-and-stare,
        i.e. slit position and raster number are combined into a single axis.
        """
        return _SnSSlicer(self)

    @property
    def slice_as_raster(self):
        """
        Method to slice instance as though data were 4D, i.e. raster number,
        slit step position, position along slit, wavelength.
        """
        return _SequenceSlicer(self)

    def __getitem__(self, item):
        raise NotImplementedError(f"Use {self.__class__.__name__}.slice_as_raster or "
                                  f"{self.__class__.__name__}.slice_as_SnS.")

    @property
    def raster_instrument_axes_types(self):
        return tuple([self._raster_axis_name] + list(self._single_scan_instrument_axes_types))

    @property
    def SnS_instrument_axes_types(self):
        return tuple([self._SnS_axis_name] + list(
            self._single_scan_instrument_axes_types[self._single_scan_instrument_axes_types !=
                                                    self._slit_step_axis_name]))


class _SnSSlicer:
    """
    Helper class to make slicing in index_as_cube sliceable/indexable like a
    numpy array.
    Parameters
    ----------
    seq : `ndcube.NDCubeSequence`
        Object of NDCubeSequence.
    """

    def __init__(self, seq):
        self.seq = seq

    def __getitem__(self, item):
        result = utils.sequence._slice_sequence_as_SnS(self.seq, item)
        if isinstance(item, tuple) and not isinstance(item[0], numbers.Integral):
            result._single_scan_instrument_axes_types = _slice_scan_axis_types(
                    self.seq._single_scan_instrument_axes_types, item)
        return result


class _SequenceSlicer:
    def __init__(self, seq):
        self.seq = seq

    def __getitem__(self, item):
        # Slice RasterSequence using parent's getitem method,
        # as RasterSequence's has be overidden with a NotImplementedError.
        result = self.seq.__class__.__bases__[0].__getitem__(self.seq, item)
        if isinstance(item, tuple):
            if isinstance(result, self.seq.__class__):
                # If slit step axis sliced out, return SpectrogramSequence
                # as the spectrogram cubes no longer represent a raster.
                if len(item) > self.seq._common_axis and \
                        isinstance(item[1:][self.seq._common_axis], numbers.Integral):
                    result = SpectrogramSequence(result.data, common_axis=None, meta=result.meta)
                else:
                    # Else, slice the instrument axis types accordingly.
                    result._single_scan_instrument_axes_types = _slice_scan_axis_types(
                        self.seq._single_scan_instrument_axes_types, item[1:])
        return result


def _slice_scan_axis_types(single_scan_axes_types, item):
    """
    Updates RasterSequence._single_scan_axes_types according to slicing.

    Parameters
    ----------
    single_scan_axes_types: `numpy.ndarray`
        Value of RasterSequence._single_scan_axes_types,
        i.e. array of strings giving type of each axis.
    
    item: `int`, `slice` or `tuple` of `slice`s.
        The slicing item that get applied to the Raster instances within the RasterSequences.

    Returns
    -------
    new_single_scan_axes_types: `numpy.ndarray`
        Update value of axis types with which to replace RasterSequence._single_scan_axes_types.

    """
    # Get boolean axes indices of axis items that aren't int,
    # i.e. axes that are not sliced away.
    not_int_axis_items = [not isinstance(axis_item, numbers.Integral) for axis_item in item]
    # Add boolean indices for axes not included in item.
    not_int_axis_items += [True] * (len(single_scan_axes_types) - len(not_int_axis_items))
    return single_scan_axes_types[np.array(not_int_axis_items)]
