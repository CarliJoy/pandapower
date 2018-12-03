# -*- coding: utf-8 -*-

# Copyright (c) 2016-2018 by University of Kassel and Fraunhofer Institute for Energy Economics
# and Energy System Technology (IEE), Kassel. All rights reserved.


import numpy as np
import numpy.core.numeric as ncn
from pandapower.idx_bus import PV, REF, VA, VM, BUS_TYPE, NONE, VMAX, VMIN, PQ
from pandapower.idx_gen import QMIN, QMAX, PMIN, PMAX, GEN_STATUS, GEN_BUS, PG, VG, QG
from pandapower.pf.ppci_variables import bustypes

def _build_gen_ppc(net, ppc):
    '''
    Takes the empty ppc network and fills it with the gen values. The gen
    datatype will be float afterwards.

    **INPUT**:
        **net** -The pandapower format network

        **ppc** - The PYPOWER format network to fill in values
    '''

    mode = net["_options"]["mode"]

    # if mode == power flow or short circuit...
    if mode in ["pf", "opf", "sc"]:

        # get in service elements
        _is_elements = net["_is_elements"]
        eg_is_mask = _is_elements['ext_grid']
        gen_is_mask = _is_elements['gen']

#        nr_gens = {element: np.sum(net["_is_elements"][element]) for element in ["ext_grid", "gen"]}

        nr_eg = np.sum(eg_is_mask)
        nr_gen = np.sum(gen_is_mask)
        nr_xward = len(net.xward)

        if mode == "opf":
            if len(net.dcline) > 0:
                ppc["dcline"] = net.dcline[["loss_mw", "loss_percent"]].values
            nr_sgen_ctrl = 0
            for element in ["load", "sgen", "storage"]:
                if "controllable" in net[element]:
                    controllable = net[element].controllable.fillna(False).values.astype(bool)
                else:
                    controllable = np.zeros(len(net[element])).astype(bool)
                in_service = _is_elements[element]
                _is_elements["%s_controllable"%element] = net[element][controllable & in_service]
            nr_load_ctrl = len(_is_elements["load_controllable"])
            nr_sgen_ctrl = len(_is_elements["sgen_controllable"])
            nr_storage_ctrl = len(_is_elements["storage_controllable"])
        else:
            nr_sgen_ctrl = 0
            nr_load_ctrl = 0
            nr_storage_ctrl = 0

        nr_generators = nr_eg + nr_gen + nr_sgen_ctrl + nr_load_ctrl + nr_storage_ctrl + nr_xward
        _init_ppc_gen(net, ppc, nr_generators)
        idx = 0

        if nr_eg > 0:
            _build_pp_ext_grid(net, ppc, idx, idx+nr_eg)
            idx += nr_eg

        if nr_gen > 0:
            _build_pp_gen(net, ppc, idx, idx+nr_gen)
            idx += nr_gen

        if nr_sgen_ctrl > 0:
            _build_pp_pq_element(net, ppc, "sgen", idx, idx+nr_sgen_ctrl)
            idx += nr_sgen_ctrl

        if nr_load_ctrl > 0:
            _build_pp_pq_element(net, ppc, "load", idx, idx+nr_load_ctrl,
                                 inverted=True)
            idx += nr_load_ctrl

        if nr_storage_ctrl > 0:
            _build_pp_pq_element(net, ppc, "storage", idx, idx+nr_storage_ctrl,
                                 inverted=True)
            idx += nr_storage_ctrl

        if nr_xward > 0:
            _build_pp_xward(net, ppc, idx, idx+nr_xward)
            idx += nr_xward

        _replace_nans_with_default_limits(net, ppc)

def _init_ppc_gen(net, ppc, nr_gens):
    # initialize generator matrix
    ppc["gen"] = np.zeros(shape=(nr_gens, 21), dtype=float)
    ppc["gen"][:] = np.array([0, 0, 0, 0, 0, 1.,
                              1., 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
#    if net._options["copy_constraints_to_ppc"]:
    q_lim_default = net._options["p_lim_default"]
    p_lim_default = net._options["p_lim_default"]
    ppc["gen"][:, PMAX] = p_lim_default
    ppc["gen"][:, PMIN] = -p_lim_default
    ppc["gen"][:, QMAX] = q_lim_default
    ppc["gen"][:, QMIN] = -q_lim_default

def _build_pp_ext_grid(net, ppc, f, t):
    delta = net._options["delta"]
    eg_is = net.ext_grid[net._is_elements["ext_grid"]]
    calculate_voltage_angles = net["_options"]["calculate_voltage_angles"]
    bus_lookup = net["_pd2ppc_lookups"]["bus"]
    # add ext grid / slack data
    eg_buses = bus_lookup[eg_is["bus"].values]
    ppc["gen"][f:t, GEN_BUS] = eg_buses
    ppc["gen"][f:t, VG] = eg_is["vm_pu"].values

    # set bus values for external grid buses
    if calculate_voltage_angles:
        ppc["bus"][eg_buses, VA] = eg_is["va_degree"].values
    ppc["bus"][eg_buses, BUS_TYPE] = REF
    ppc["bus"][eg_buses, VM] = eg_is["vm_pu"].values
    # _build_gen_lookups(net, "ext_grid", 0, eg_end)
#    if net["_options"]["copy_constraints_to_ppc"]:
    if net._options["mode"] == "opf":
        add_q_constraints(ppc, eg_is, f, t, delta)
        add_p_constraints(ppc, eg_is, f, t, delta)
        ppc["bus"][eg_buses, VMAX] = ppc["bus"][ppc["bus"][:, BUS_TYPE] == REF, VM]
        ppc["bus"][eg_buses, VMIN] = ppc["bus"][ppc["bus"][:, BUS_TYPE] == REF, VM]
    else:
        ppc["gen"][f:t, QMIN] = 0
        ppc["gen"][f:t, QMAX] = 0

        # REF busses don't have flexible voltages by definition:


def _build_pp_gen(net, ppc, f, t):
    delta = net["_options"]["delta"]
    gen_is = net.gen[net._is_elements["gen"]]
    bus_lookup = net["_pd2ppc_lookups"]["bus"]

    gen_buses = bus_lookup[gen_is["bus"].values]
    gen_is_vm = gen_is["vm_pu"].values
    ppc["gen"][f:t, GEN_BUS] = gen_buses
    ppc["gen"][f:t, PG] = (gen_is["p_mw"].values* gen_is["scaling"].values)
    ppc["gen"][f:t, VG] = gen_is_vm

    # set bus values for generator buses
    ppc["bus"][gen_buses[ppc["bus"][gen_buses, BUS_TYPE] != REF], BUS_TYPE] = PV

    if any(gen_is["slack"].values):
        slack_buses = gen_is["bus"][gen_is["slack"]].values
        ppc["bus"][bus_lookup[slack_buses], BUS_TYPE] = REF

    ppc["bus"][gen_buses, VM] = gen_is_vm
    add_q_constraints(ppc, gen_is, f, t, delta)
    add_p_constraints(ppc, gen_is, f, t, delta)
#    else:
#        q_lim_default = net._options["q_lim_default"]
#        ppc["gen"][f:t, QMIN] = -q_lim_default
#        ppc["gen"][f:t, QMAX] = q_lim_default


def _build_pp_xward(net, ppc, f, t, update_lookup=True):
    delta = net["_options"]["delta"]
    q_lim_default = net._options["q_lim_default"]
    bus_lookup = net["_pd2ppc_lookups"]["bus"]
    xw = net["xward"]
    xw_is = net["_is_elements"]['xward']
    if update_lookup:
        ppc["gen"][f:t, GEN_BUS] = bus_lookup[xw["ad_bus"].values]
    ppc["gen"][f:t, VG] = xw["vm_pu"].values
    ppc["gen"][f:t, GEN_STATUS] = xw_is
    ppc["gen"][f:t, PMIN] = + delta
    ppc["gen"][f:t, PMAX] = - delta
    ppc["gen"][f:t, QMIN] = -q_lim_default
    ppc["gen"][f:t, QMAX] = q_lim_default

    xward_buses = bus_lookup[net["xward"]["ad_bus"].values]
    ppc["bus"][xward_buses[xw_is], BUS_TYPE] = PV
    ppc["bus"][xward_buses[~xw_is], BUS_TYPE] = NONE
    ppc["bus"][xward_buses, VM] = net["xward"]["vm_pu"].values

def _build_pp_pq_element(net, ppc, element, f, t, inverted=False):
    delta = net._options["delta"]
    sign = -1 if inverted else 1
    tab = net._is_elements["%s_controllable"%element]
    bus_lookup = net["_pd2ppc_lookups"]["bus"]
    buses = bus_lookup[tab["bus"].values]

    ppc["gen"][f:t, GEN_BUS] = buses
    ppc["gen"][f:t, PG] = sign * tab["p_mw"].values * tab["scaling"].values
    ppc["gen"][f:t, QG] = sign * tab["q_mvar"].values * tab["scaling"].values

    # set bus values for controllable loads
#    ppc["bus"][buses, BUS_TYPE] = PQ
    add_q_constraints(ppc, tab, f, t, delta, inverted)
    add_p_constraints(ppc, tab, f, t, delta, inverted)


def add_q_constraints(ppc, tab, f, t, delta, inverted=False):
    if "min_q_mvar" in tab.columns:
        if inverted:
            ppc["gen"][f:t, QMAX] = -tab["min_q_mvar"].values + delta
        else:
            ppc["gen"][f:t, QMIN] = tab["min_q_mvar"].values - delta
    if "max_q_mvar" in tab.columns:
        if inverted:
            ppc["gen"][f:t, QMIN] = -tab["max_q_mvar"].values - delta
        else:
            ppc["gen"][f:t, QMAX] = tab["max_q_mvar"].values + delta

def add_p_constraints(ppc, tab, f, t, delta, inverted=False):
    if "min_p_mw" in tab.columns:
        if inverted:
            ppc["gen"][f:t, PMAX] = - tab["min_p_mw"].values + delta
        else:
            ppc["gen"][f:t, PMIN] = tab["min_p_mw"].values - delta
    if "max_p_mw" in tab.columns:
        if inverted:
            ppc["gen"][f:t, PMIN] = - tab["max_p_mw"].values - delta
        else:
            ppc["gen"][f:t, PMAX] = tab["max_p_mw"].values + delta


def _update_gen_ppc(net, ppc):
    '''
    Takes the ppc network and updates the gen values from the values in net.

    **INPUT**:
        **net** -The pandapower format network

        **ppc** - The PYPOWER format network to fill in values
    '''
    # get options from net
    calculate_voltage_angles = net["_options"]["calculate_voltage_angles"]
    bus_lookup = net["_pd2ppc_lookups"]["bus"]
    # get in service elements
    _is_elements = net["_is_elements"]
    eg_is = net["ext_grid"][_is_elements['ext_grid']]
    gen_is = net["gen"][_is_elements['gen']]

    eg_end = len(eg_is)
    gen_end = eg_end + len(gen_is)
    xw_end = gen_end + len(net["xward"])

    # add ext grid / slack data
    ext_grid_lookup = net["_pd2ppc_lookups"]["ext_grid"]
    ext_grid_idx_ppc = ext_grid_lookup[eg_is.index]
    ppc["gen"][ext_grid_idx_ppc, VG] = eg_is["vm_pu"].values
    ppc["gen"][ext_grid_idx_ppc, GEN_STATUS] = eg_is["in_service"].values

    # set bus values for external grid buses
    if calculate_voltage_angles:
        # eg_buses = bus_lookup[eg_is["bus"].values]
        ppc["bus"][ext_grid_idx_ppc, VA] = eg_is["va_degree"].values

    # add generator / pv data
    if gen_end > eg_end:
        gen_lookup = net["_pd2ppc_lookups"]["gen"]
        gen_idx_ppc = gen_lookup[gen_is.index]
        ppc["gen"][gen_idx_ppc, PG] = gen_is["p_mw"].values * gen_is["scaling"].values
        ppc["gen"][gen_idx_ppc, VG] = gen_is["vm_pu"].values

        # set bus values for generator buses
        gen_buses = bus_lookup[gen_is["bus"].values]
        ppc["bus"][gen_buses, VM] = gen_is["vm_pu"].values

        add_q_constraints(ppc, gen_is, gen_end, eg_end, net._options["delta"])

    # add extended ward pv node data
    if xw_end > gen_end:
        # ToDo: this must be tested in combination with recycle. Maybe the placement of the updated value in ppc["gen"]
        # ToDo: is wrong. -> I'll better raise en error
        raise NotImplementedError("xwards in combination with recycle is not properly implemented")
        # _build_pp_xward(net, ppc, gen_end, xw_end, q_lim_default,
        #                           update_lookup=False)
    _replace_nans_with_default_limits(net, ppc)

def _replace_nans_with_default_limits(net, ppc):
    qlim = net._options["q_lim_default"]
    plim = net._options["p_lim_default"]

    for ppc_column, default in [(QMAX, qlim), (QMIN, -qlim), (PMIN, -plim), (PMAX, plim)]:
        limits = ppc["gen"][:, [ppc_column]]
        ncn.copyto(limits, default, where=np.isnan(limits))
        ppc["gen"][:, [ppc_column]] = limits

def _check_voltage_setpoints_at_same_bus(ppc):
    # generator buses:
    gen_bus = ppc['gen'][:, GEN_BUS].astype(int)
    # generator setpoints:
    gen_vm = ppc['gen'][:, VG]
    if _different_values_at_one_bus(gen_bus, gen_vm):
        raise UserWarning("Generators with different voltage setpoints connected to the same bus")

def _check_voltage_angles_at_same_bus(net, ppc):
    if net._is_elements["ext_grid"].any():
        gen_va = net.ext_grid.va_degree[net._is_elements["ext_grid"]].values
        eg_gens = net._pd2ppc_lookups["ext_grid"][net.ext_grid.index[net._is_elements["ext_grid"]]]
        gen_bus = ppc["gen"][eg_gens, GEN_BUS].astype(int)
        if _different_values_at_one_bus(gen_bus, gen_va):
            raise UserWarning("Ext grids with different voltage angle setpoints connected to the same bus")

def _check_for_reference_bus(ppc):
    ref, _, _ = bustypes(ppc["bus"], ppc["gen"])
    # throw an error since no reference bus is defined
    if len(ref) == 0:
        raise UserWarning("No reference bus is available. Either add an ext_grid or a gen with slack=True")


def _different_values_at_one_bus(buses, values):
    """
    checks if there are different values in any of the

    """
    # buses with one or more generators and their index
    unique_bus, index_first_bus = np.unique(buses, return_index=True)

    # voltage setpoint lookup with the voltage of the first occurence of that bus
    first_values = -np.ones(buses.max() + 1)
    first_values[unique_bus] = values[index_first_bus]

    # generate voltage setpoints where all generators at the same bus
    # have the voltage of the first generator at that bus
    values_equal = first_values[buses]

    return not np.array_equal(values, values_equal)