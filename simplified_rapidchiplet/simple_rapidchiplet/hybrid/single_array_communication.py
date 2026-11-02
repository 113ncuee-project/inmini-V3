"""Paid consumer read cohorts for the smaller shared v0.2 L2.

Historical Gemini could retain multi-group/tile multicast data in a large
per-core GLB. v0.2 may reload from materialized DRAM instead of requiring that
unbounded retention. Every additional cohort copy pays real IO/NoP/DMA/L2.
Temporal/group/layer/tile cohorts also prevent a single atomic multicast
waiting for a future recipient bank which depends on an earlier recipient.
Within-cohort multicast remains shared. Persistent weights retain their
explicit policy and are still subject to the shared WL2 lifetime check.
"""
from dataclasses import replace


VERSION = 'single_array_consumer_cohort_v1'


def split_read_cohorts(compiled, communication):
    units = compiled.unit_map
    transfers, replacement = [], {}
    for transfer in communication.transfers:
        if transfer.kind == 'dram_weight' or not transfer.consumer_units:
            transfers.append(transfer)
            continue
        cohorts = {}
        for name in transfer.consumer_units:
            unit = units[name]
            cohorts.setdefault((unit.group_id, unit.layer_id, unit.tile_index, unit.execution_order), []).append(name)
        if len(cohorts) <= 1:
            transfers.append(transfer)
            continue
        for index, (_, users) in enumerate(sorted(cohorts.items())):
            identifier = f'{transfer.id}:cohort{index}'
            destinations = tuple(dict.fromkeys(units[name].chiplet for name in users))
            transfers.append(replace(transfer, id=identifier, dsts=destinations, consumer_units=tuple(users)))
            for name in users:
                replacement[(transfer.id, name)] = identifier
    dependencies = tuple((name, tuple(dict.fromkeys(replacement.get((dependency, name), dependency)
                         for dependency in deps))) for name, deps in communication.unit_dependencies)
    # These metadata lifetimes are unused by the v0.2 allocator: it derives
    # arrival-to-last-reader intervals directly from the realized transfers.
    return replace(communication, transfers=tuple(transfers), unit_dependencies=dependencies)
