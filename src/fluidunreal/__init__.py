"""fluidunreal: bring a hand-off bundle into Unreal Engine 5 and prove what arrived.

The engine-side twin of fluidblend. It imports what fluidblend published, measures what the editor
really wrote, plays it in its own test bed and publishes evidence. It never edits a Blender source:
when a fix belongs there, it writes a typed fluidblend request and hands over.
"""

from fluidblend.contracts.common import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION", "__version__"]
__version__ = "0.1.0"
