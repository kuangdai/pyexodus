#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:copyright:
    Lion Krischer (lionkrischer@gmail.com), 2016
:license:
    MIT License
"""
from __future__ import absolute_import

import os
import platform

import numpy as np

import h5netcdf


class exodus(object):
    """
    Create a new Exodus file. Can also be used as a context manager.

    :type file: str
    :param file: Filename
    :type mode: str
    :param mode: File mode. Must currently be ``"w"``.
    :type array_type: str
    :param array_type: Must be ``"numpy"``.
    :type title: str
    :param title: The title of the mesh.
    :type numDims: int
    :param numDims: The number of dimensions.
    :type numNodes: int
    :param numNodes: The number of nodes.
    :type numElems: int
    :param numElems: The number of elements.
    :type numBlocks: int
    :param numBlocks: The number of element blocks.
    :type numNodeSets: int
    :param numNodeSets: The number of node side sets.
    :type numSideSets: int
    :param numSideSets: The number of element side sets.
    :type io_size: int
    :param io_size: Determines how floating point variables are stored in
        the file.  Inputs will be converted if required.

        * ``0``: machine precision
        * ``4``: single precision
        * ``8``: double precision
    :type compression: tuple
    :param compression: Turn on compression. Pass a tuple of
        ``(method, option)``, e.g. ``("gzip", 2)``. Slows down writing a lot
        but the resulting files are potentially much smaller.
    """
    def __init__(self, file, mode="r", array_type="numpy", title=None,
                 numDims=None, numNodes=None, numElems=None, numBlocks=None,
                 numNodeSets=None, numSideSets=None, io_size=0,
                 compression=None):

        if compression:
            self._comp_opts = {
                "chunks": True,
                "compression": compression[0],
                "compression_opts": compression[1]}
        else:
            self._comp_opts = {}

        # API is currently quite limited...mainly because nothing else is
        # implemented.
        assert mode == "w", "Currently only writing is supported."
        assert array_type == "numpy", "array_type must be 'numpy'."
        assert numNodeSets == 0, "numNodeSets must be 0 for now."
        assert numDims in [2, 3], "Only 2 or 3 dimensions are supported."

        # Determines the precision with which floating point variables are
        # written.
        if io_size == 0:
            if platform.architecture()[0] == "64bit":  # pragma: no cover
                self.__f_dtype = np.float64
                self.__f_word_size = 8
            else:  # pragma: no cover
                self.__f_dtype = np.float32
                self.__f_word_size = 4
        elif io_size == 4:
            self.__f_dtype = np.float32
            self.__f_word_size = 4
        elif io_size == 8:
            self.__f_dtype = np.float64
            self.__f_word_size = 8
        else:  # pragma: no cover
            raise NotImplementedError

        assert not os.path.exists(file), "File '%s' already exists." % file

        self._f = h5netcdf.File(file)

        self._write_attrs(title=title)

        # Set the dimensions - very straightforward.
        # XXX: These should come from some header variable.
        self._f.dimensions["len_string"] = 33
        self._f.dimensions["len_line"] = 81
        # No clue what this is for...
        self._f.dimensions["four"] = 4
        self._f.dimensions["len_name"] = 33

        # XXX: Currently must be set to one as h5netcdf does currently
        # not support unlimited dimensions altough this should be easy
        # to add.
        self._f.dimensions["time_step"] = 1

        # These are dynamic.
        self._f.dimensions["num_dim"] = numDims
        self._f.dimensions["num_nodes"] = numNodes
        self._f.dimensions["num_elem"] = numElems
        self._f.dimensions["num_el_blk"] = numBlocks
        if numSideSets:
            self._f.dimensions["num_side_sets"] = numSideSets

        self._create_variables()

    def put_info_records(self, info):
        """
        Puts the info records into the exodus file.

        Does currently not do anything.

        :type info: list of str
        :param info: The strings to save.
        """
        if not info:
            return

        for _i, value in enumerate(info):
            assert len(value) < self._f.dimensions["len_line"], \
                "Records '%s' is longer then %i letters." % (
                    value, self._f.dimensions["len_line"])

        self._f.dimensions["num_info"] = len(info)

        self._f.create_variable(
            "info_records", ("num_info", "len_line"),
            dtype="|S1", **self._comp_opts)

        ir = self._f.variables["info_records"]
        for idx, value in enumerate(info):
            # Clear just to be safe.
            ir[idx] = b""
            if not value:
                continue
            ir[idx, :len(value)] = [_i.encode() if hasattr(_i, "encode")
                                    else _i for _i in value]

    def put_coords(self, xCoords, yCoords, zCoords):
        """
        Put coordinates in the exodus file.

        :type xCoords: :class:`numpy.ndarray`
        :param xCoords: The X coordiantes.
        :type yCoords: :class:`numpy.ndarray`
        :param yCoords:  The Y coordinates.
        :type zCoords: :class:`numpy.ndarray`
        :param zCoords:  The Z coordinates.
        """
        self._f.variables["coordx"][:] = xCoords
        self._f.variables["coordy"][:] = yCoords
        self._f.variables["coordz"][:] = zCoords

    def put_elem_blk_info(self, id, elemType, numElems, numNodesPerElem,
                          numAttrsPerElem):
        """
        Set the details of an element block.

        :type id: int
        :param id: The id of the element block.
        :type elemType: str
        :param elemType: The name of the element block.
        :type numElems: int
        :param numElems: The number of elements in the block.
        :type numNodesPerElem: int
        :param numNodesPerElem: The number of nodes per element.
        :type numAttrsPerElem: int
        :param numAttrsPerElem: The number of attributes per element.
        """
        assert numElems <= self._f.dimensions["num_elem"], \
            "Canont have more elements in the block then globally set."
        assert numAttrsPerElem == 0, "Must be 0 for now."

        # So the logic is as follows. `eb_status` keeps track of which
        # element ids have already been assigned. We find the first that is
        # not zero and that is the actual index of the the element block.
        status = self._f._variables["eb_status"][:]
        assert 0 in status, "All element blocks already set."
        idx = np.argwhere(status == 0)[0][0] + 1

        num_el_name = "num_el_in_blk%i" % idx
        num_node_per_el_name = "num_nod_per_el%i" % idx
        var_name = "connect%i" % idx

        self._f.dimensions[num_el_name] = numElems
        self._f.dimensions[num_node_per_el_name] = numNodesPerElem

        self._f.create_variable(
            var_name, (num_el_name, num_node_per_el_name),
            dtype=np.int32, **self._comp_opts)
        self._f.variables[var_name].attrs['elem_type'] = np.string_(elemType)

        # Set the status and thus "claim" the element block id.
        self._f.variables['eb_status'][idx - 1] = 1
        # For some reason this is always eb_prop1.
        self._f.variables['eb_prop1'][idx - 1] = id

    def put_elem_connectivity(self, id, connectivity, shift_indices=0,
                              chunk_size_in_mb=128):
        """
        Set the element connectivity array for all elements in a block.

        The information for this block must have already been set by calling
        e.put_elem_blk_info() on this block.

        :type id: int
        :param id: The id of the element block.
        :type connectivity: :class:`numpy.ndarray`
        :param connectivity: The connectivity. Must be equal to the number
            of of elements times the number of nodes per element for any
            given block.
        :type shift_indices: int
        :param shift_indices: **Not available in the official exodus Python
            API!** This value will be added to all indices before they are
            written to the file. This is useful if you for example
            internally work with a 0-based indexing scheme but exodus
            requires a 1-based indexing scheme.
        :type chunk_size_in_mb: int
        :param chunk_size_in_mb: If ``shift_indices`` != 0 values will be
            written in chunks of this size. This is also the maximum memory
            usage of this method. If ``shift_indices`` == 0, all indices
            will be written directly from memory and no additional memory is
            required.
        """
        num_el_name = "num_el_in_blk%i" % id
        num_node_per_el_name = "num_nod_per_el%i" % id
        var_name = "connect%i" % id

        assert num_el_name in self._f.dimensions, \
            "Block id %i does not exist" % id
        assert num_node_per_el_name in self._f.dimensions, \
            "Block id %i does not exist" % id

        assert connectivity.size == (
            self._f.dimensions[num_el_name] *
            self._f.dimensions[num_node_per_el_name])

        if shift_indices:
            ne = self._f.dimensions[num_el_name]
            nn = self._f.dimensions[num_node_per_el_name]

            chunk_size = int(chunk_size_in_mb * 1024 ** 2 /
                             connectivity.dtype.itemsize / nn)

            _t = connectivity.reshape((ne, nn))

            idx = 0
            while idx < ne:
                self._f.variables[var_name][idx: idx+chunk_size] = \
                    _t[idx: idx+chunk_size] + shift_indices
                idx += chunk_size
        else:
            self._f.variables[var_name][:] = \
                connectivity.reshape((
                    self._f.dimensions[num_el_name],
                    self._f.dimensions[num_node_per_el_name]))

    def put_time(self, step, value):
        """
        Put time step and value into exodus file.

        :type step: int
        :param step: The index of the time step. First is 1.
        :type value: float
        :param value: The actual time at that index.
        """
        assert step > 0, "Step must be larger than 0."
        # XXX: Currently the time axis is not unlimited due to a limitation
        # in h5netcdf - thus no new time steps can be created after the
        # initialization.
        assert step <= self._f.dimensions["time_step"]

        self._f.variables["time_whole"][step - 1] = value

    def set_global_variable_number(self, number):
        """
        Set number of global variables in exodus file.

        :type number: int
        :param number: The number of global variables.
        """
        if not number:  # pragma: no cover
            return

        self._f.dimensions["num_glo_var"] = number

        self._f.create_variable(
            "name_glo_var", ("num_glo_var", "len_name"),
            dtype="|S1", **self._comp_opts)
        self._f.create_variable(
            "vals_glo_var", ("time_step", "num_glo_var"),
            dtype=self.__f_dtype, **self._comp_opts)

    def put_global_variable_name(self, name, index):
        """
        Put global variable with name at index into exodus file.

        :type name: str
        :param name: The name of the variable.
        :type index: int
        :param index: The index of the global variable. First is 1!
        """
        self._f.variables["name_glo_var"][index - 1] = b""
        self._f.variables["name_glo_var"][index - 1, :len(name)] = \
            [_i.encode() if hasattr(_i, "encode") else _i for _i in name]

    def put_global_variable_value(self, name, step, value):
        """
        Put global variable value and variable name at time step into exodus
        file.

        :type name: str
        :param name: The name of the variable.
        :type step: int
        :param step: The index of the time step. First is 1.
        :type value: float
        :param value: The actual time at that index.
        """
        assert step > 0, "Step must be larger than 0."
        # XXX: Currently the time axis is not unlimited due to a limitation
        # in h5netcdf - thus no new time steps can be created after the
        # initialization.
        assert step <= self._f.dimensions["time_step"]

        idx = self.get_global_variable_names().index(name)
        self._f.variables["vals_glo_var"][step - 1, idx] = value

    def get_global_variable_names(self):
        """
        Get list of global variable names in exodus file.
        """
        return [b"".join(_i).strip().decode()
                for _i in self._f.variables["name_glo_var"][:]]

    def set_element_variable_number(self, number):
        """
        Set number of element variables in exodus file.

        :type number: int
        :param number: The number of variables per element.
        """
        if not number:
            return

        self._f.dimensions["num_elem_var"] = number

        self._f.create_variable(
            "name_elem_var", ("num_elem_var", "len_name"),
            dtype="|S1", **self._comp_opts)

    def put_element_variable_name(self, name, index):
        """
        Element variable with name at index into exodus file.

        :type name: str
        :param name: The name of the element variable.
        :type index: int
        :param index: The index of the element variable. Starts with 1!
        """
        self._f.variables["name_elem_var"][index - 1] = b""
        self._f.variables["name_elem_var"][index - 1, :len(name)] = \
            [_i.encode() if hasattr(_i, "encode") else _i for _i in name]

    def get_element_variable_names(self):
        """
        Get list of element variable names in exodus file.
        """
        return [b"".join(_i).strip().decode()
                for _i in self._f.variables["name_elem_var"][:]]

    def put_element_variable_values(self, blockId, name, step, values):
        """
        Put values into element block id and variable name at step.

        :type blockId: int
        :param blockId: The block id.
        :type name: str
        :param name: The name of the variable.
        :type step: int
        :param step: The time step at which to put the values.
        :type values: :class:`numpy.ndarray`
        :param values: The actual values.
        """
        assert step > 0, "Step must be larger than 0."
        # XXX: Currently the time axis is not unlimited due to a limitation
        # in h5netcdf - thus no new time steps can be created after the
        # initialization.
        assert step <= self._f.dimensions["time_step"]

        num_elem_name = "num_el_in_blk%i" % blockId
        assert num_elem_name in self._f.dimensions, \
            "Block id %i not found." % blockId

        # 1-based indexing!
        idx = self.get_element_variable_names().index(name) + 1

        variable_name = "vals_elem_var%ieb%i" % (idx, blockId)

        # If it does not exist, create it.
        if variable_name not in self._f.variables:
            self._f.create_variable(
                variable_name, ("time_step", num_elem_name),
                dtype=self.__f_dtype, **self._comp_opts)

        self._f.variables[variable_name][step - 1] = values

    def set_node_variable_number(self, number):
        """
        Set number of node variables in exodus file.

        :type number: int
        :param number: The number of node variables.
        """
        if number == 0:  # pragma: no cover
            return

        self._f.dimensions["num_nod_var"] = number

        self._f.create_variable(
            "name_nod_var", ("num_nod_var", "len_name"),
            dtype="|S1", **self._comp_opts)

        for _i in range(number):
            name = "vals_nod_var%i" % (_i + 1)
            self._f.create_variable(
                name, ("time_step", "num_nodes"),
                dtype=self.__f_dtype, **self._comp_opts)

    def put_node_variable_name(self, name, index):
        """
        Node variable with name at index into exodus file.

        :type name: str
        :param name: The name of the element variable.
        :type index: int
        :param index: The index of the element variable. Starts with 1!
        """
        # 1 - based indexing!
        assert index <= self._f.dimensions["num_nod_var"]

        self._f.variables["name_nod_var"][index - 1] = b""
        self._f.variables["name_nod_var"][index - 1, :len(name)] = \
            [_i.encode() if hasattr(_i, "encode") else _i for _i in name]

    def get_node_variable_names(self):
        """
        Get list of node variable names in exodus file.
        """
        return [b"".join(_i).strip().decode()
                for _i in self._f.variables["name_nod_var"][:]]

    def put_node_variable_values(self, name, step, values):
        """
        Put node values into variable name at step into exodus file

        :type name: str
        :param name: The name of the variable.
        :type step: int
        :param step: The time step at which to put the values.
        :type values: :class:`numpy.ndarray`
        :param values: The actual values.
        """
        assert step > 0, "Step must be larger than 0."
        # XXX: Currently the time axis is not unlimited due to a limitation
        # in h5netcdf - thus no new time steps can be created after the
        # initialization.
        assert step <= self._f.dimensions["time_step"]

        # 1-based indexing!
        idx = self.get_node_variable_names().index(name) + 1

        d_name = "vals_nod_var%i" % idx
        self._f.variables[d_name][step - 1] = values

    def put_side_set_params(self, id, numSetSides, numSetDistFacts):
        """
        Set ID, num elements, and num nodes of a sideset

        :type id: int
        :param id: The id of the side set.
        :type numSetSides: int
        :param numSetSides: The number of elements for a side set.
        :type numSetDistFacts: int
        :param numSetDistFacts: The number of nodes for the side set.
        """
        assert numSetDistFacts == 0, "Only 0 is currently supported."

        assert id not in self._f.variables["ss_prop1"][:], \
            "Side set id %i already exists." % id

        _t = self._f.variables["ss_status"][:]
        count = len(_t[_t > 0])
        assert count < self._f.dimensions["num_side_sets"],  \
            "Maximum number of side sets reached."

        idx = count + 1
        dim_name = "num_side_ss%i" % idx
        elem_ss_name = "elem_ss%i" % idx
        side_ss_name = "side_ss%i" % idx

        # Create the dimension and variables.
        self._f.dimensions[dim_name] = numSetSides
        self._f.create_variable(elem_ss_name, (dim_name,), dtype=np.int32,
                                **self._comp_opts)
        self._f.create_variable(side_ss_name, (dim_name,), dtype=np.int32,
                                **self._comp_opts)

        # Set meta-data.
        self._f.variables["ss_status"][idx - 1] = 1
        # For reasons I don't understand, this is ALWAYS ss_prop1.
        self._f.variables["ss_prop1"][idx - 1] = id

    def put_side_set(self, id, sideSetElements, sideSetSides):
        """
        Set the id, element ids, and side ids for a side set (creates the
        side set).

        :type id: int
        :param id: The id of the side set.
        :type sideSetElements: :class:`numpy.ndarray`
        :param sideSetElements: The side set elements.
        :type sideSetSides: :class:`numpy.ndarray`
        :param sideSetSides: The side set sides.
        """
        # Find the side set.
        _idx = self._f.variables["ss_prop1"][:]
        assert id in _idx, "Could not find side set with id %i." % id
        # 1-based indexing!
        idx = np.argwhere(_idx == id)[0][0] + 1

        elem_ss_name = "elem_ss%i" % idx
        side_ss_name = "side_ss%i" % idx

        self._f.variables[elem_ss_name][:] = sideSetElements
        self._f.variables[side_ss_name][:] = sideSetSides

    def put_side_set_name(self, id, name):
        """
        Write side set name for side set "id" in exodus file

        :type id: int
        :param id: The id of the side set.
        :type name: str
        :param name: The string of the side set.
        """
        # Find the side set.
        _idx = self._f.variables["ss_prop1"][:]
        assert id in _idx, "Could not find side set with id %i." % id
        # 1-based indexing!
        idx = np.argwhere(_idx == id)[0][0] + 1

        self._f.variables["ss_names"][idx - 1] = b""
        self._f.variables["ss_names"][idx - 1, :len(name)] = \
            [_i.encode() if hasattr(_i, "encode") else _i for _i in name]

    def _write_attrs(self, title):
        """
        Write all the attributes.
        """
        # XXX: Should probably all be defined in some header file.
        self._f.attrs['api_version'] = np.float32([6.30000019])
        self._f.attrs['version'] = np.float32([6.30000019])
        self._f.attrs['floating_point_word_size'] = \
            np.array([self.__f_word_size], dtype=np.int32)
        self._f.attrs['file_size'] = np.array([1], dtype=np.int32)
        self._f.attrs['maximum_name_length'] = np.array([32],
                                                        dtype=np.int32)
        self._f.attrs['int64_status'] = np.array([0], dtype=np.int32)
        self._f.attrs['title'] = np.string_(title)

    def _create_variables(self):
        # Coordinate names.
        self._f.create_variable('/coor_names', ('num_dim', 'len_name'),
                                dtype='|S1', **self._comp_opts)

        # Coordinates.
        for i in "xyz":
            self._f.create_variable(
                '/coord' + i, ('num_nodes',), dtype=self.__f_dtype,
                **self._comp_opts)

        # Element block stuff.
        self._f.create_variable('/eb_names', ('num_el_blk', 'len_name'),
                                dtype='|S1', **self._comp_opts)
        # I don't really understand the number here yet...
        self._f.create_variable('/eb_prop1', ('num_el_blk',),
                                dtype=np.int32,
                                data=[-1] * self._f.dimensions['num_el_blk'],
                                **self._comp_opts)
        self._f.variables["eb_prop1"].attrs['name'] = np.string_('ID')
        self._f.create_variable('/eb_status', ('num_el_blk',),
                                dtype=np.int32, **self._comp_opts)

        # Side sets.
        if "num_side_sets" in self._f.dimensions:
            self._f.create_variable(
                '/ss_names', ('num_side_sets', 'len_name'), dtype='|S1',
                **self._comp_opts)
            self._f.create_variable(
                '/ss_prop1', ('num_side_sets',), dtype=np.int32,
                data=[-1] * self._f.dimensions["num_side_sets"],
                **self._comp_opts)
            self._f.variables["ss_prop1"].attrs['name'] = np.string_('ID')
            self._f.create_variable('/ss_status', ('num_side_sets',),
                                    dtype=np.int32, **self._comp_opts)

        # Time steps.
        self._f.create_variable('/time_whole', ('time_step',),
                                dtype=self.__f_dtype, **self._comp_opts)

    def __del__(self):
        try:
            self._f.close()
        except:  # pragma: no cover
            pass

    def close(self):
        try:
            self._f.close()
        except:  # pragma: no cover
            pass

    def __enter__(self):
        """
        Enable usage as a context manager.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Enable usage as a context manager.
        """
        self.__del__()
