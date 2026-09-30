"""snappnt: snapshot PNT receiver toolkit for low-cost front ends.

Layers (see docs/design/architecture.md):
  signals   what signal to receive (carrier, chip rate, spreading codes)
  frontend  how it is received (device limits, frequency plan)
  io        how data moves between layers (SigMF files, device I/O)
  sim       synthetic signals with known truth
  rx        acquisition and measurements
  eval      detection-probability sweeps and truth comparison
"""

__version__ = "0.0.1"
