"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import option_item_sp

# ndm: stock A_CRUISE_MAX_VALS at A_CRUISE_MAX_BP = [0, 10, 25, 40] m/s, used to render
# the resulting accel ceiling in the description so the percentage means something.
_STOCK_ACCEL = (("0", 1.6), ("22", 1.2), ("56", 0.8), ("89", 0.6))
_STOCK_DECEL = 1.2          # A_CRUISE_MIN
_STOCK_COMFORT_BRAKE = 2.5  # COMFORT_BRAKE in long_mpc.py
_ACCEL_MAX = 2.0    # opendbc ACCEL_MAX; also the panda limit in safety/modes/rivian.h
_ACCEL_MIN = 3.5    # opendbc ACCEL_MIN, as a magnitude
_M_TO_FT = 3.281


class RivianSettings(BrandSettings):
  def __init__(self):
    super().__init__()

    # ndm: max steering-wheel angle before MADS releases lateral control (stock 90°).
    # Backed by RivianMaxSteeringAngle; applied live by card.py (no restart needed).
    self.max_steering_angle = option_item_sp(
      title=lambda: tr("Maximum Lateral Steering Angle"),
      param="RivianMaxSteeringAngle",
      min_value=30,
      max_value=720,
      value_change_step=30,
      description="",
      label_callback=lambda v: f"{v}°",
    )

    # ndm: longitudinal comfort tuning. Backed by RivianAccelProfile / RivianDecelProfile /
    # RivianComfortBrake / RivianStopDistance; read once a second by plannerd (no restart).
    self.accel_profile = option_item_sp(
      title=lambda: tr("Acceleration Aggressiveness"),
      param="RivianAccelProfile",
      min_value=100,
      max_value=200,
      value_change_step=10,
      description="",
      label_callback=lambda v: f"{v}%",
    )

    self.decel_profile = option_item_sp(
      title=lambda: tr("Deceleration Aggressiveness"),
      param="RivianDecelProfile",
      min_value=100,
      max_value=200,
      value_change_step=10,
      description="",
      label_callback=lambda v: f"{v}%",
    )

    self.comfort_brake = option_item_sp(
      title=lambda: tr("Lead Braking Assertiveness"),
      param="RivianComfortBrake",
      min_value=80,
      max_value=150,
      value_change_step=10,
      description="",
      label_callback=lambda v: f"{v}%",
    )

    self.stop_distance = option_item_sp(
      title=lambda: tr("Stopping Distance"),
      param="RivianStopDistance",
      min_value=3,
      max_value=10,
      value_change_step=1,
      description="",
      label_callback=lambda v: f"{v} m",
    )

    self.items = [
      self.max_steering_angle,
      self.accel_profile,
      self.decel_profile,
      self.comfort_brake,
      self.stop_distance,
    ]

  def update_settings(self):
    offroad = ui_state.is_offroad()

    base_desc = tr("Maximum steering wheel angle openpilot will hold before it releases lateral control. " +
                   "Stock is 90°. Higher values let it follow tighter, lower-speed turns, but commanding the " +
                   "torque-steered rack to large angles is experimental — test at low speed.")
    disabled_msg = tr("Turn the vehicle off to change this setting.")
    desc = base_desc if offroad else f"<b>{disabled_msg}</b><br><br>{base_desc}"

    self.max_steering_angle.set_description(desc)
    self.max_steering_angle.action_item.set_enabled(offroad)

    self.accel_profile.set_description(self._accel_description())
    self.decel_profile.set_description(self._decel_description())
    self.comfort_brake.set_description(self._comfort_brake_description())
    self.stop_distance.set_description(self._stop_distance_description())

  def _accel_description(self) -> str:
    scale = self.accel_profile.action_item.get_value() / 100.0
    table = ", ".join(f"{mph} mph: {min(a * scale, _ACCEL_MAX):.1f}" for mph, a in _STOCK_ACCEL)

    desc = tr("Scales how hard openpilot accelerates on cruise. 100% is stock openpilot, which is very " +
              "conservative on the R1 — only 0.8 m/s² at 56 mph. Higher values scale the acceleration, " +
              "jerk and combined lateral+longitudinal limits together, up to the 2.0 m/s² ceiling the " +
              "panda enforces.")
    note = tr("Only applies in normal (chill) mode — Experimental Mode already allows the full 2.0 m/s².")

    return f"{desc}<br><br><b>{tr('Resulting limit')}</b> — {table} m/s²<br><br>{note}"

  def _decel_description(self) -> str:
    limit = min(_STOCK_DECEL * self.decel_profile.action_item.get_value() / 100.0, _ACCEL_MIN)

    desc = tr("Scales how hard openpilot slows down to reach a lower set speed or speed limit. Stock is " +
              "-1.2 m/s². This does not change braking for a lead car — that comes from the model and is " +
              "controlled by the two settings below.")

    return f"{desc}<br><br><b>{tr('Resulting limit')}</b> — -{limit:.1f} m/s²"

  def _comfort_brake_description(self) -> str:
    percent = self.comfort_brake.action_item.get_value()

    desc = tr("How much braking authority the planner assumes it has when closing on a slower or stopped " +
              "lead. Higher values approach faster and brake later and harder; lower values start braking " +
              "earlier and more gently. This does not change your following distance at steady speed — " +
              "that is the personality button.")
    warn = tr("Above 100% openpilot leaves itself less room to stop. Raise it one step at a time.")

    prefix = f"<b>{warn}</b><br><br>" if percent > 100 else ""
    authority = _STOCK_COMFORT_BRAKE * percent / 100.0

    return f"{desc}<br><br>{prefix}<b>{tr('Braking authority')}</b> — {authority:.2f} m/s²"

  def _stop_distance_description(self) -> str:
    meters = self.stop_distance.action_item.get_value()

    desc = tr("How far behind a stopped car openpilot comes to rest. Stock is 6 m.")

    return f"{desc}<br><br><b>{tr('Gap')}</b> — {meters} m ({meters * _M_TO_FT:.0f} ft)"
