"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car import structs
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL

# ndm: user-adjustable Rivian longitudinal tuning (no restart required).
#
# Stock openpilot's comfort limits are far below what the R1 and the panda allow,
# which makes cruise acceleration unusable on the highway (0.8 m/s^2 at 56 mph).
# These four knobs scale the limits toward the hard ceilings, which are unchanged:
# ACCEL_MAX 2.0 / ACCEL_MIN -3.5 m/s^2, matching RIVIAN_LONG_LIMITS in the panda
# (opendbc/safety/modes/rivian.h).
#
#   accel_scale    A_CRUISE_MAX_VALS, J_CRUISE_VALS and _A_TOTAL_MAX_V in
#                  longitudinal_planner.get_cruise_accel -- the accel ceiling,
#                  how fast it ramps into it, and the combined lat+long budget.
#   decel_scale    A_CRUISE_MIN, the cruise-source decel floor (-1.2 stock). Only
#                  applies to closing on the set speed, not to lead braking.
#   comfort_brake  COMFORT_BRAKE in the long MPC (2.5 stock). Sets how much braking
#                  authority the planner assumes when closing on a slower lead:
#                  higher means it approaches faster and brakes later and harder.
#                  It cancels out at steady state, so it does not change following
#                  distance -- that is t_follow (the personality button).
#   stop_distance  STOP_DISTANCE in the long MPC (6.0 m stock), the gap it leaves
#                  behind a stopped lead.
#   lead_danger_factor
#                  LEAD_DANGER_FACTOR (0.75 stock). The 4th MPC constraint is a slacked
#                  gap >= lead_danger_factor * desired_dist carrying DANGER_ZONE_COST
#                  (100), while the distance cost pulls to desired_dist itself. So this
#                  does not move the steady-state gap -- it sets how close the car may
#                  get before that heavy penalty fights back, which is what shapes
#                  cut-ins and closing on a slower lead.
#   follow_scale   trims T_FOLLOW, the selected personality's headway. The steady-state
#                  gap is t_follow * v + stop_distance -- the only two terms there are --
#                  so this is the only knob that scales following distance with speed.
#                  Floored at 10% rather than 0 at the owner's request, for testing on
#                  their own vehicle. t_follow is the entire speed-dependent part of the
#                  gap, so at 0 the target collapses to stop_distance at every speed
#                  (6 m at 70 mph) and there is no headway left to solve for; 10% keeps
#                  a speed-dependent term. 10% is 0.32 s at 70 mph on aggressive -- far
#                  inside any reaction margin. Default stays 100% and the UI warns in
#                  three tiers below it.
#
# comfort_brake and stop_distance are acados runtime parameters (p[6], p[7]) rather
# than compiled-in constants -- see the ndm edits in long_mpc.py.
DEFAULTS = {
  "RivianAccelProfile": (100, 100, 200),   # percent of stock, (default, min, max)
  "RivianDecelProfile": (100, 100, 200),   # percent of stock
  "RivianComfortBrake": (100, 80, 150),    # percent of stock
  "RivianStopDistance": (6, 3, 10),        # meters
  "RivianFollowDistance": (100, 10, 100),  # percent of the selected personality's T_FOLLOW
  "RivianLeadDanger": (75, 10, 100),       # LEAD_DANGER_FACTOR x100
}

STOCK_COMFORT_BRAKE = 2.5
STOCK_STOP_DISTANCE = 6.0
STOCK_LEAD_DANGER = 0.75


class RivianLongTuning:
  """Frame-throttled read of the Rivian longitudinal tuning params."""

  def __init__(self, CP: structs.CarParams, params=None):
    self._params = params or Params()
    self._enabled = CP.brand == "rivian"
    self._frame = 0

    self.accel_scale = 1.0
    self.decel_scale = 1.0
    self.comfort_brake = STOCK_COMFORT_BRAKE
    self.stop_distance = STOCK_STOP_DISTANCE
    self.follow_scale = 1.0
    self.lead_danger_factor = STOCK_LEAD_DANGER
    self._read_params()

  def _get(self, key: str) -> int:
    # Runs in plannerd's control loop, so never raise -- any failure (bad or missing
    # value, param read error) falls back to stock. Clamp rather than trust the
    # stored value: these feed control limits, so a stale or hand-edited param must
    # never push them outside the range the UI offers.
    default, lo, hi = DEFAULTS[key]
    try:
      value = int(self._params.get(key, return_default=True))
    except Exception:
      value = default

    return min(max(value, lo), hi)

  def _read_params(self) -> None:
    if not self._enabled:
      return

    self.accel_scale = self._get("RivianAccelProfile") / 100.0
    self.decel_scale = self._get("RivianDecelProfile") / 100.0
    self.comfort_brake = STOCK_COMFORT_BRAKE * self._get("RivianComfortBrake") / 100.0
    self.stop_distance = float(self._get("RivianStopDistance"))
    self.follow_scale = self._get("RivianFollowDistance") / 100.0
    self.lead_danger_factor = self._get("RivianLeadDanger") / 100.0

  def update(self) -> None:
    if self._frame % int(1. / DT_MDL) == 0:
      self._read_params()
    self._frame += 1
