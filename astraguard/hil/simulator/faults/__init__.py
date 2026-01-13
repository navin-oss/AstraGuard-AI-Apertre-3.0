"""HIL fault injection models for CubeSat subsystems."""

from .power_brownout import PowerBrownoutFault
from .comms_dropout import CommsDropoutFault

__all__ = ["PowerBrownoutFault", "CommsDropoutFault"]
