"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import opendbc.sunnypilot.car.rivian.mads as rivian_mads
from openpilot.common.params import Params

# ndm: live Rivian steering-angle-limit override (no restart required).
#
# The stock sunnypilot Rivian MADS controller drops lateral control once the
# steering wheel passes MAX_STEERING_ANGLE (default 90 deg) — see
# opendbc/sunnypilot/car/rivian/mads.py. That constant lives inside the opendbc
# submodule, which the device clones pristine, so it can't be edited from this
# (parent) repo and deployed. Instead we override the module-level constant at
# runtime from card.py's params loop. `mads_status_update` resolves the name at
# call time, so reassigning it here takes effect on the next control frame.
DEFAULT_MAX_STEERING_ANGLE = 90.0


def update_rivian_max_steering_angle(params: Params) -> None:
  # Runs in card.py's params loop (critical), so never raise — any failure
  # (bad/missing value, param read error) falls back to the stock cutoff.
  try:
    value = float(params.get("RivianMaxSteeringAngle", return_default=True))
  except Exception:
    value = DEFAULT_MAX_STEERING_ANGLE
  rivian_mads.MAX_STEERING_ANGLE = value
