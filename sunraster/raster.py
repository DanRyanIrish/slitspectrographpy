import textwrap

import astropy.units as u
import ndcube.utils.sequence
import numpy as np
from ndcube import NDCube, NDCubeSequence
from ndcube.utils.cube import convert_extra_coords_dict_to_input_format

from sunraster import utils

__all__ = ['Raster', 'RasterSequence']

# Define some custom error messages.
APPLY_EXPOSURE_TIME_ERROR = ("Exposure time correction has probably already "
                             "been applied since the unit already includes "
                             "inverse time. To apply exposure time correction "
                             "anyway, set 'force' kwarg to True.")
UNDO_EXPOSURE_TIME_ERROR = ("Exposure time correction has probably already "
                            "been undone since the unit does not include "
                            "inverse time. To undo exposure time correction "
                            "anyway, set 'force' kwarg to True.")
AXIS_NOT_FOUND_ERROR = " axis not found. If in extra_coords, axis name must be supported: "

# Define supported coordinate names for coordinate properties.
SUPPORTED_LONGITUDE_NAMES = [".lon", "longitude", "lon"]
SUPPORTED_LONGITUDE_NAMES += [name.upper() for name in SUPPORTED_LONGITUDE_NAMES]
SUPPORTED_LONGITUDE_NAMES += [name.capitalize() for name in SUPPORTED_LONGITUDE_NAMES]

SUPPORTED_LATITUDE_NAMES = [".lat", "latitude", "lat"]
SUPPORTED_LATITUDE_NAMES += [name.upper() for name in SUPPORTED_LATITUDE_NAMES]
SUPPORTED_LATITUDE_NAMES += [name.capitalize() for name in SUPPORTED_LATITUDE_NAMES]

SUPPORTED_SPECTRAL_NAMES = ["em.wl", "em.energy", "em.freq", "wavelength", "energy",
                            "frequency", "freq", "lambda"]
SUPPORTED_SPECTRAL_NAMES += [name.upper() for name in SUPPORTED_SPECTRAL_NAMES]
SUPPORTED_SPECTRAL_NAMES += [name.capitalize() for name in SUPPORTED_SPECTRAL_NAMES]

SUPPORTED_TIME_NAMES = ["time"]
SUPPORTED_TIME_NAMES += [name.upper() for name in SUPPORTED_TIME_NAMES]
SUPPORTED_TIME_NAMES += [name.capitalize() for name in SUPPORTED_TIME_NAMES]

SUPPORTED_EXPOSURE_NAMES = ["exposure time", "exposure_time", "exposure times",
                            "exposure_times", "exp time", "exp_time", "exp times", "exp_times"]
SUPPORTED_EXPOSURE_NAMES += [name.upper() for name in SUPPORTED_EXPOSURE_NAMES]
SUPPORTED_EXPOSURE_NAMES += [name.capitalize() for name in SUPPORTED_EXPOSURE_NAMES]

class RasterSequence(NDCubeSequence):
    """
    Class for holding, slicing and plotting spectrogram data.

    This class contains all the functionality of its super class with
    some additional functionalities.

    Parameters
    ----------
    data_list: `list`
        List of `Raster` objects from the same spectral window and OBS ID.
        Must also contain the 'detector type' in its meta attribute.

    meta: `dict` or header object
        Metadata associated with the sequence.

    slit_step_axis: `int`
        The axis of the Raster instances corresponding to time.
    """
    def __init__(self, data_list, slit_step_axis=0, meta=None):
        # Initialize Sequence.
        super().__init__(data_list, common_axis=slit_step_axis, meta=meta)
        self._slit_step_axis = self._common_axis
        self._sequence_axis = 0
        self._sequence_axis_name = self.world_axis_physical_types[self._sequence_axis]

    raster_dimensions = NDCubeSequence.dimensions
    SnS_dimensions = NDCubeSequence.cube_like_dimensions
    raster_world_axis_physical_types = NDCubeSequence.world_axis_physical_types
    SnS_world_axis_physical_types = NDCubeSequence.cube_like_world_axis_physical_types
    raster_axis_extra_coords = NDCubeSequence.sequence_axis_extra_coords
    SnS_axis_extra_coords = NDCubeSequence.common_axis_extra_coords
    plot_as_raster = NDCubeSequence.plot
    plot_as_SnS = NDCubeSequence.plot_as_cube

    def __str__(self):
        if self.data[0]._time_name:
            time_period = (self.data[0].time[0].value, self.data[-1].time[-1].value)
        else:
            time_period = None
        if self.data[0]._longitude_name:
            lon_range = u.Quantity([self.lon.min(), self.lon.max()])
        else:
            lon_range = None
        if self.data[0]._latitude_name:
            lat_range = u.Quantity([self.lat.min(), self.lat.max()])
        else:
            lat_range = None
        if self.data[0]._spectral_name:
            spectral_range = u.Quantity([self.spectral.min(), self.spectral.max()])
        else:
            spectral_range = None
        return (textwrap.dedent(f"""\
                RasterSequence
                --------------
                Time Range: {time_period}
                Pixel Dimensions (raster scans, slit steps, slit height, spectral): {self.dimensions}
                Longitude range: {lon_range}
                Latitude range: {lat_range}
                Spectral range: {spectral_range}
                Data unit: {self.data[0].unit}"""))

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

    @property
    def spectral(self):
        return u.Quantity([raster.spectral for raster in self.data])

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
        result: `None` or `RasterSequence`
            If copy=False, the original RasterSequence is modified with the
            exposure time correction applied (undone).
            If copy=True, a new RasterSequence is returned with the correction
            applied (undone).
        """
        converted_data_list = []
        for cube in self.data:
            converted_data_list.append(cube.apply_exposure_time_correction(undo=undo,
                                                                           force=force))
        if copy is True:
            return RasterSequence(
                converted_data_list, meta=self.meta, common_axis=self._common_axis)
        else:
            self.data = converted_data_list

    def _raster_axes_to_world_types(self, *axes, include_extra_coords=True):
        """
        Retrieve the world axis physical types for each pixel axis.

        This differs from world_axis_physical_types in that it provides an explicit
        mapping between pixel axes and physical types, including dependent physical
        types.

        Parameters
        ----------
        axes: `int` or multiple `int`
            Axis number in numpy ordering of axes for which real world physical types
            are desired.
            axes=None implies axis names for all axes will be returned.

        include_extra_coords: `bool`
           If True, also search extra_coords for coordinate corresponding to axes.
           Default=True.

        Returns
        -------
        axes_names: `tuple` of `str`
            The world axis physical types corresponding to each axis.
            If more than one physical type found for an axis, that axis's entry will
            be a tuple of `str`.
        """
        # Parse user input.
        if axes == ():
            axes = np.arange(len(self.dimensions))
        elif isinstance(axes, int):
            axes = np.array([axes])
        else:
            axes = np.array(axes)

        n_axes = len(axes)
        axes_names = [None] * n_axes

        # If sequence axis in axes, get names for it separately.
        if self._sequence_axis in axes:
            sequence_names_indices = np.array([axis == self._sequence_axis for axis in axes])
            # Get standard sequence axis name from world_axis_physical_types.
            sequence_axes_names = [self._sequence_axis_name]
            # If desired, get extra coord sequence axis names.
            if include_extra_coords:
                extra_sequence_names = utils.sequence._get_axis_extra_coord_names_and_units(
                        self.data, None)[0]
                if extra_sequence_names:
                    sequence_axes_names += list(extra_sequence_names)
            # Enter sequence axis names into output.
            # Must use for loop as can't assign tuples to multiple array location
            # with indexing and setitem.
            for i in np.arange(n_axes)[sequence_names_indices]:
                axes_names[i] = tuple(sequence_axes_names)

            # Get indices of axes numbers associated with cube axes.
            cube_indices = np.invert(sequence_names_indices)
            cube_axes = axes[cube_indices] - 1
        else:
            cube_indices = np.ones(n_axes, dtype=bool)
            cube_axes = axes

        # Get world types from cube axes.
        if len(cube_axes) > 0:
            cube_axes_names = self.data[0]._pixel_axes_to_world_types(
                    *cube_axes, include_extra_coords=include_extra_coords)
            for i, name in zip(np.arange(n_axes)[cube_indices], cube_axes_names):
                axes_names[i] = name

        return tuple(axes_names)

    def _world_types_to_raster_axes(self, *axes_names, include_extra_coords=True):
        """
        Retrieve the pixel axes (numpy ordering) corresponding to each world axis physical type.

        Parameters
        ----------
        axes_names: `str` or multiple `str`
            world axis physical types for which the pixel axis numbers are desired.
            axes_names=None implies all axes will be returned.

        include_extra_coords: `bool`
           If True, also search extra_coords for axis name.
           Default=True.

        Returns
        -------
        axes: `tuple` of `int`
            The pixel axis numbers (numpy ordering) that correspond to the supplied
            axis names.
            If more than one axis corresponds to the physical type, that physical type's
            entry in the output will be a tuple of `int`.
            If no axes names supplied, the ordering of the axis numbers returned will
            correspond to the physical types returned by NDCube.world_axis_physical_types.
        """
        # Parse user input.
        if axes_names == ():
            axes_names = np.array(self.world_axis_physical_types)
        elif isinstance(axes_names, str):
            axes_names = np.array([axes_names])
        else:
            axes_names = np.array(axes_names)
        n_names = len(axes_names)
        axes = np.array([None] * n_names, dtype=object)

        # Get world types associated with sequence axis.
        sequence_axes_names = [self._sequence_axis_name]
        # If desired, also get extra coord sequence axis names.
        if include_extra_coords:
            extra_sequence_names = utils.sequence._get_axis_extra_coord_names_and_units(self.data, None)[0]
                    self.data, None)[0]
            if extra_sequence_names:
                sequence_axes_names += list(extra_sequence_names)
        sequence_axes_names = np.asarray(sequence_axes_names)
        # Find indices of axes_names that correspond to sequence axis and
        # and enter axis number to output
        sequence_names_indices = np.isin(axes_names, sequence_axes_names)
        axes[sequence_names_indices] = self._sequence_axis

        # Get indices of cube axis names and use Raster version of this method to get axis numbers.
        cube_names_indices = np.invert(sequence_names_indices)
        if cube_names_indices.any():
            axes[cube_names_indices] = self.data[0].world_types_to_pixel_axes(
                    *axes_names[cube_names_indices], include_extra_coords=include_extra_coords)

        return tuple(axes)


class Raster(NDCube):
    """
    Class representing a sit-and-stare or single raster of slit spectrogram
    data.

    Must be described by a single WCS.

    Parameters
    ----------
    data: `numpy.ndarray`
        The array holding the actual data in this object.

    wcs: `ndcube.wcs.wcs.WCS`
        The WCS object containing the axes' information

    unit : `astropy.unit.Unit` or `str`
        Unit for the dataset. Strings that can be converted to a Unit are allowed.

    meta : dict-like object
        Additional meta information about the dataset.

    uncertainty : any type, optional
        Uncertainty in the dataset. Should have an attribute uncertainty_type
        that defines what kind of uncertainty is stored, for example "std"
        for standard deviation or "var" for variance. A metaclass defining
        such an interface is NDUncertainty - but isn’t mandatory. If the uncertainty
        has no such attribute the uncertainty is stored as UnknownUncertainty.
        Defaults to None.

    mask : any type, optional
        Mask for the dataset. Masks should follow the numpy convention
        that valid data points are marked by False and invalid ones with True.
        Defaults to None.

    extra_coords : iterable of `tuple`s, each with three entries
        (`str`, `int`, `astropy.units.quantity` or array-like)
        Gives the name, axis of data, and values of coordinates of a data axis not
        included in the WCS object.

    copy : `bool`, optional
        Indicates whether to save the arguments as copy. True copies every attribute
        before saving it while False tries to save every parameter as reference.
        Note however that it is not always possible to save the input as reference.
        Default is False.
    """
    def __init__(self, data, wcs, extra_coords=None, unit=None, uncertainty=None, meta=None,
                 mask=None, copy=False, missing_axes=None):
        # Initialize Raster.
        super().__init__(data, wcs, uncertainty=uncertainty, mask=mask, meta=meta, unit=unit,
                         extra_coords=extra_coords, copy=copy, missing_axes=missing_axes)

        # Determine labels and location of each key real world coordinate.
        self._longitude_name = self._find_axis_name(SUPPORTED_LONGITUDE_NAMES)
        self._latitude_name = self._find_axis_name(SUPPORTED_LATITUDE_NAMES)
        self._spectral_name = self._find_axis_name(SUPPORTED_SPECTRAL_NAMES)
        self._time_name = self._find_axis_name(SUPPORTED_TIME_NAMES)
        self._exposure_time_name = self._find_axis_name(SUPPORTED_EXPOSURE_NAMES)

    def __str__(self):
        if self._time_name:
            time_period = (self.time[0], self.time[-1])
        else:
            time_period = None
        if self._longitude_name:
            lon_range = u.Quantity([self.lon.min(), self.lon.max()])
        else:
            lon_range = None
        if self._latitude_name:
            lat_range = u.Quantity([self.lat.min(), self.lat.max()])
        else:
            lat_range = None
        if self._spectral_name:
            spectral_range = u.Quantity([self.spectral.min(), self.spectral.max()])
        else:
            spectral_range = None
        return (textwrap.dedent(f"""\
                Raster
                ------
                Time Period: {time_period}
                Pixel dimensions (Slit steps, Slit height, Spectral): {self.dimensions}
                Longitude range: {lon_range}
                Latitude range: {lat_range}
                Spectral range: {spectral_range}
                Data unit: {self.unit}"""))

    def __getitem__(self, item):
        result = super().__getitem__(item)
        if result.extra_coords is None:
            extra_coords = None
        else:
            extra_coords = convert_extra_coords_dict_to_input_format(result.extra_coords,
                                                                     result.missing_axes)
        return self.__class__(result.data, result.wcs, extra_coords, result.unit,
                              result.uncertainty, result.meta, mask=result.mask,
                              missing_axes=result.missing_axes)

    @property
    def spectral(self):
        if not self._spectral_name:
            raise ValueError("Spectral" + AXIS_NOT_FOUND_ERROR + \
                             f"{SUPPORTED_SPECTRAL_NAMES}")
        else:
            return self._get_axis_coord(*self._spectral_name)

    @property
    def time(self):
        if not self._time_name:
            raise ValueError("Time" + AXIS_NOT_FOUND_ERROR + \
                             f"{SUPPORTED_TIMES_NAMES}")
        else:
            return self._get_axis_coord(*self._time_name)

    @property
    def exposure_time(self):
        if not self._exposure_time_name:
            raise ValueError("Exposure time" + AXIS_NOT_FOUND_ERROR + \
                             f"{SUPPORTED_EXPOSURE_NAMES}")
        else:
            return self._get_axis_coord(*self._exposure_time_name)

    @property
    def lon(self):
        if not self._longitude_name:
            raise ValueError("Longitude" + AXIS_NOT_FOUND_ERROR + \
                             f"{SUPPORTED_LONGITUDE_NAMES}")
        else:
            return self._get_axis_coord(*self._longitude_name)

    @property
    def lat(self):
        if not self._latitude_name:
            raise ValueError("Latitude" + AXIS_NOT_FOUND_ERROR + \
                             f"{SUPPORTED_LATITUDE_NAME}")
        else:
            return self._get_axis_coord(*self._latitude_name)

    def apply_exposure_time_correction(self, undo=False, force=False):
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
            If True, exposure time correction is undone.
            Default=False

        force: `bool`
            If not True, applies (undoes) exposure time correction only if unit
            doesn't (does) already include inverse time.
            If True, correction is applied (undone) regardless of unit.  Unit is still
            adjusted accordingly.

        Returns
        -------
        result: `Raster`
            New Raster in new units.
        """
        # Get exposure time in seconds and change array's shape so that
        # it can be broadcast with data and uncertainty arrays.
        exposure_time_s = self.exposure_time.to(u.s).value
        if not np.isscalar(exposure_time_s):
            if len(self.dimensions) == 1:
                pass
            elif len(self.dimensions) == 2:
                exposure_time_s = exposure_time_s[:, np.newaxis]
            elif len(self.dimensions) == 3:
                exposure_time_s = exposure_time_s[:, np.newaxis, np.newaxis]
            else:
                raise ValueError(
                    "Raster dimensions must be 2 or 3. Dimensions={}".format(
                        len(self.dimensions.shape)))
        # Based on value on undo kwarg, apply or remove exposure time correction.
        if undo is True:
            new_data_arrays, new_unit = _uncalculate_exposure_time_correction(
                (self.data, self.uncertainty.array), self.unit, exposure_time_s, force=force)
        else:
            new_data_arrays, new_unit = _calculate_exposure_time_correction(
                (self.data, self.uncertainty.array), self.unit, exposure_time_s, force=force)
        # Return new instance of Raster with correction applied/undone.
        return Raster(
            new_data_arrays[0], self.wcs,
            convert_extra_coords_dict_to_input_format(self.extra_coords, self.missing_axes),
            new_unit, new_data_arrays[1], self.meta, mask=self.mask, missing_axes=self.missing_axes)

    def _pixel_axes_to_world_types(self, *args, include_extra_coords=True):
        """
        Retrieve the world axis physical types for each pixel axis.

        This differs from world_axis_physical_types in that it provides an explicit
        mapping between pixel axes and physical types, including dependent physical
        types.

        Parameters
        ----------
        axes: `int` or multiple `int`
            Axis number in numpy ordering of axes for which real world physical types
            are desired.
            axes=None implies axis names for all axes will be returned.

        include_extra_coords: `bool`
           If True, also search extra_coords for coordinate corresponding to axes.
           Default=True.

        Returns
        -------
        axes_names: `tuple` of `str`
            The world axis physical types corresponding to each axis.
            If more than one physical type found for an axis, that axis's entry will
            be a tuple of `str`.
        """
        # Define the dimensions of the cube and the total number of axes.
        n_dimensions = len(self.dimensions)
        world_axis_types = np.array(self.world_axis_physical_types)
        wcs_axis_correlation_matrix = self.wcs.axis_correlation_matrix

        # Parse user input.
        if axes == ():
            axes = tuple(range(n_dimensions))
        elif isinstance(axes, int):
            axes = (axes,)

        # If extra coords axis name desired, invert extra_coords so that
        # keys are axis numbers and values are axis names.
        if include_extra_coords:
            extra_coords = self.extra_coords
            extra_coords_axes = dict([('None', [])] + [(str(i), []) for i in range(n_dimensions)])
            for key in extra_coords.keys():
                coord_axes = extra_coords[key]["axis"]
                if isinstance(coord_axes, numbers.Integral) or coord_axes is None:
                    extra_coords_axes[str(coord_axes)].append(key)
                else:
                    for coord_axis in coord_axes:
                        extra_coords_axes[str(coord_axis)].append(key)

        # For each axis, get axis names from WCS and extra coords, if desired.
        n_axes = len(axes)
        axes_names = [None] * n_axes
        for axis in axes:
            # If axis number is negative, convert to corresponding positive version.
            # This is not needed for WCS operation as this check it performed by
            # data_axis_to_wcs_axis. But it is needed for extra_coords, and doing
            # conversion here should not slow down WCS case and prevent it being done twice
            # if extra coords axis type desired.
            if axis < 0:
                axis = n_dimensions + axis
            # Get axis types from WCS.
            axis_names = world_axis_types[wcs_axis_correlation_matrix[
                data_axis_to_wcs_axis(axis, self.missing_axes)]]
            # Get axis types from extra coords if desired.
            if include_extra_coords:
                str_axis = str(axis)
                if str_axis in extra_coords_axes.keys():
                    axis_names = list(set(list(axis_names) + extra_coords_axes[str_axis]))
            # Enter axes into output.
            if len(axis_names) == 1:
                axes_names[i] = axis_names[0]
            else:
                axes_names[i] = tuple(axis_names)
 
    def _world_types_to_pixel_axes(self, *axes_names, include_extra_coords=True):
        """
        Retrieve the pixel axes (numpy ordering) corresponding to each world axis physical type.

        Parameters
        ----------
        axes_names: `str` or multiple `str`
            world axis physical types for which the pixel axis numbers are desired.
            axes_names=None implies all axes will be returned.

        include_extra_coords: `bool`
           If True, also search extra_coords for axis name.
           Default=True.

        Returns
        -------
        axes: `tuple` of `int`
            The pixel axis numbers (numpy ordering) that correspond to the supplied
            axis names.
            If more than one axis corresponds to the physical type, that physical type's
            entry in the output will be a tuple of `int`.
            If no axes names supplied, the ordering of the axis numbers returned will
            correspond to the physical types returned by NDCube.world_axis_physical_types.
        """
        wcs_names = self.world_axis_physical_types
        extra_coords = self.extra_coords

        # Parse user input.
        if axes_names == ():
            axes_names = wcs_names
        elif isinstance(axes_names, str):
            axes_names = (axes_names,)

        n_names = len(axes_names)
        axes = [None] * n_names
        for i, name in enumerate(axes_names):
            # Ensure axis number is an int or int equivalent.
            if not isinstance(name, str):
                raise TypeError("axis names must be strings. Offending axis name: "
                                f"{name}; type = {type(name)}")

            # Check WCS an extra coords for physical type.
            try:
                axis = utils.cube.get_axis_number_from_axis_name(name, wcs_names)
                name_in_wcs = True
                # Determine any dependent axes.
                dependent_axes = utils.wcs.get_dependent_data_axes(self.wcs, axis,
                                                                   self.missing_axes)
            except ValueError:
                name_in_wcs = False

            # Check extra_coords for axis name if user wants to check extra coords.
            if include_extra_coords:
                w_axis_from_extra_coords = [name in key for key in extra_coords.keys()]
                n_instances_in_extra_coords = sum(w_axis_from_extra_coords)
                if (name_in_wcs and n_instances_in_extra_coords > 0) or n_instances_in_extra_coords > 1:
                    raise ValueError("axis name provided not unique.")
                elif n_instances_in_extra_coords == 1:
                    dependent_axes = extra_coords[name]["axis"]

            # Enter axes into list.
            if isinstance(dependent_axes, numbers.Integral) or len(dependent_axes) != 1:
                axes[i] = dependent_axes
            else:
                axes[i] = dependent_axes[0]

        return tuple(axes)

    def _find_axis_name(self, supported_names):
        axis_name = None
        n_names = len(supported_names)
        if self.extra_coords is not None:
            extra_coord_keys = self.extra_coords.keys()
        else:
            extra_coord_keys = None
        i = 0
        while axis_name is None:
            if i >= n_names:
                break
            # Check WCS.
            wcs_name_index = ([supported_names[i] in world_axis_type
                               for world_axis_type in self.world_axis_physical_types])
            if sum(wcs_name_index) == 1:
                wcs_name_index = \
                        int(np.arange(len(self.world_axis_physical_types))[wcs_name_index])
                axis_name = self.world_axis_physical_types[wcs_name_index]
                loc = "wcs"

            # If label not contained in WCS, check extra coords.
            if axis_name is None and extra_coord_keys is not None:
                if supported_names[i] in extra_coord_keys:
                    axis_name = supported_names[i]
                    loc = "extra_coords"
            i += 1

        if axis_name is None:
            return axis_name
        else:
            return (axis_name, loc)

    def _get_axis_coord(self, axis_name, coord_loc):
        if coord_loc == "wcs":
            return self.axis_world_coords(axis_name)
        elif coord_loc == "extra_coords":
            return self.extra_coords[axis_name]["value"]


def _calculate_exposure_time_correction(old_data_arrays, old_unit, exposure_time,
                                        force=False):
    """
    Applies exposure time correction to data arrays.
    Parameters
    ----------
    old_data_arrays: iterable of `numpy.ndarray`s
        Arrays of data to be converted.
    old_unit: `astropy.unit.Unit`
        Unit of data arrays.
    exposure_time: `numpy.ndarray`
        Exposure time in seconds for each exposure in data arrays.
    Returns
    -------
    new_data_arrays: `list` of `numpy.ndarray`s
        Data arrays with exposure time corrected for.
    new_unit_time_accounted: `astropy.unit.Unit`
        Unit of new data arrays after exposure time correction.
    """
    # If force is not set to True and unit already includes inverse time,
    # raise error as exposure time correction has probably already been
    # applied and should not be applied again.
    if force is not True and u.s in old_unit.decompose().bases:
        raise ValueError(APPLY_EXPOSURE_TIME_ERROR)
    else:
        # Else, either unit does not include inverse time and so
        # exposure does need to be applied, or
        # user has set force=True and wants the correction applied
        # regardless of the unit.
        new_data_arrays = [old_data/exposure_time for old_data in old_data_arrays]
        new_unit = old_unit/u.s
    return new_data_arrays, new_unit


def _uncalculate_exposure_time_correction(old_data_arrays, old_unit,
                                          exposure_time, force=False):
    """
    Removes exposure time correction from data arrays.
    Parameters
    ----------
    old_data_arrays: iterable of `numpy.ndarray`s
        Arrays of data to be converted.
    old_unit: `astropy.unit.Unit`
        Unit of data arrays.
    exposure_time: `numpy.ndarray`
        Exposure time in seconds for each exposure in data arrays.
    Returns
    -------
    new_data_arrays: `list` of `numpy.ndarray`s
        Data arrays with exposure time correction removed.
    new_unit_time_accounted: `astropy.unit.Unit`
        Unit of new data arrays after exposure time correction removed.
    """
    # If force is not set to True and unit does not include inverse time,
    # raise error as exposure time correction has probably already been
    # undone and should not be undone again.
    if force is not True and u.s in (old_unit*u.s).decompose().bases:
        raise ValueError(UNDO_EXPOSURE_TIME_ERROR)
    else:
        # Else, either unit does include inverse time and so
        # exposure does need to be removed, or
        # user has set force=True and wants the correction removed
        # regardless of the unit.
        new_data_arrays = [old_data * exposure_time for old_data in old_data_arrays]
        new_unit = old_unit*u.s
    return new_data_arrays, new_unit


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
        return utils.sequence._slice_sequence_as_SnS(self.seq, item)


class _SequenceSlicer:
    def __init__(self, seq):
        self.seq = seq

    def __getitem__(self, item):
        return ndcube.utils.sequence.slice_sequence(self.seq, item)
