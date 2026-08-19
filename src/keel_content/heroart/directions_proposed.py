"""Kept as a name only: the candidate directions were adopted into `DIRECTIONS`.

This module stays so an older import does not break, and so the next batch of
candidates has an obvious place to live while it is being looked at.
"""
from .directions import (BranchSpine, CompassRose, MeasuredBars, NarrowingFunnel,
                         NestedRings, QuadrantMatrix, RecordCard, SealRow, SignalRows,
                         SingleDial, StationTrack, WeighingBeam)

PROPOSED = [MeasuredBars(), NestedRings(), StationTrack(), NarrowingFunnel(),
            QuadrantMatrix(), BranchSpine(), WeighingBeam(), SingleDial(),
            RecordCard(), CompassRose(), SignalRows(), SealRow()]
