"""Kept as a name only: the fifteen candidates were adopted into `DIRECTIONS`.

They moved into `directions.py` once they had been reviewed. This module stays so an
older import does not break, and so the next batch of candidates has an obvious place
to live while it is being looked at.
"""
from .directions import (BranchSpine, CompassRose, MeasuredBars, NarrowingFunnel,
                         NestedRings, PinField, QuadrantMatrix, RecordCard, SealRow,
                         SignalRows, SingleDial, StationTrack, SteppedStrata,
                         TokenStacks, WeighingBeam)

PROPOSED = [MeasuredBars(), NestedRings(), StationTrack(), NarrowingFunnel(),
            QuadrantMatrix(), BranchSpine(), TokenStacks(), WeighingBeam(),
            PinField(), SteppedStrata(), SingleDial(), RecordCard(), CompassRose(),
            SignalRows(), SealRow()]
