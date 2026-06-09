"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import option_item_sp


class RivianSettings(BrandSettings):
  def __init__(self):
    super().__init__()

    # ndm: max steering-wheel angle before MADS releases lateral control (stock 90°).
    # Backed by RivianMaxSteeringAngle; applied live by card.py (no restart needed).
    self.max_steering_angle = option_item_sp(
      title=lambda: tr("Maximum Lateral Steering Angle"),
      param="RivianMaxSteeringAngle",
      min_value=30,
      max_value=330,
      value_change_step=30,
      description="",
      label_callback=lambda v: f"{v}°",
    )

    self.items = [self.max_steering_angle]

  def update_settings(self):
    offroad = ui_state.is_offroad()

    base_desc = tr("Maximum steering wheel angle openpilot will hold before it releases lateral control. " +
                   "Stock is 90°. Higher values let it follow tighter, lower-speed turns, but commanding the " +
                   "torque-steered rack to large angles is experimental — test at low speed.")
    disabled_msg = tr("Turn the vehicle off to change this setting.")
    desc = base_desc if offroad else f"<b>{disabled_msg}</b><br><br>{base_desc}"

    self.max_steering_angle.set_description(desc)
    self.max_steering_angle.action_item.set_enabled(offroad)
