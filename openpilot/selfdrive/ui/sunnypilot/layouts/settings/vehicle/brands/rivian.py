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

# ndm: LongitudinalPersonality enum value -> (label, T_FOLLOW) from long_mpc.get_T_FOLLOW.
# The personality button is the only thing that moves T_FOLLOW, and T_FOLLOW is the only
# term in the follow-distance formula that scales with speed, so every longitudinal
# setting below states whether the personality applies to it.
_PERSONALITIES = ((0, "Aggressive", 1.25), (1, "Standard", 1.45), (2, "Relaxed", 1.75))
_DEFAULT_PERSONALITY = 1

# reference speed the descriptions quote distances at
_REF_MPH, _REF_KPH = 70, 110
_MPH_TO_MS, _KPH_TO_MS = 0.44704, 1 / 3.6


def _active_personality() -> int:
  # Renders every frame, so never raise -- fall back to Standard on any read failure.
  try:
    return int(ui_state.params.get("LongitudinalPersonality", return_default=True))
  except Exception:
    return _DEFAULT_PERSONALITY


def _ref_speed() -> tuple[float, str]:
  """Reference speed the descriptions quote distances at, as (m/s, label)."""
  if ui_state.is_metric:
    return _REF_KPH * _KPH_TO_MS, f"{_REF_KPH} km/h"
  return _REF_MPH * _MPH_TO_MS, f"{_REF_MPH} mph"


def _distance(meters: float) -> str:
  return f"{meters:.0f} m" if ui_state.is_metric else f"{meters * _M_TO_FT:.0f} ft"


def _personality_note(applies: bool) -> str:
  """One line on every longitudinal setting saying whether the personality button
  changes it, naming the personality currently selected."""
  if not applies:
    return tr("Not affected by the personality button.")

  label = next((name for value, name, _ in _PERSONALITIES if value == _active_personality()), "Standard")
  return tr("Affected by the personality button — currently <b>{}</b>.").format(tr(label))


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
    # RivianFollowDistance / RivianComfortBrake / RivianStopDistance; read once a second
    # by plannerd (no restart needed).
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

    self.follow_distance = option_item_sp(
      title=lambda: tr("Follow Distance"),
      param="RivianFollowDistance",
      min_value=30,
      max_value=100,
      value_change_step=5,
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
      self.follow_distance,
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
    self.follow_distance.set_description(self._follow_distance_description())
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

    return (f"{desc}<br><br><b>{tr('Resulting limit')}</b> — {table} m/s²"
            f"<br><br>{note}<br>{_personality_note(False)}")

  def _decel_description(self) -> str:
    limit = min(_STOCK_DECEL * self.decel_profile.action_item.get_value() / 100.0, _ACCEL_MIN)

    desc = tr("Scales how hard openpilot slows down to reach a lower set speed or speed limit. Stock is " +
              "-1.2 m/s². This does not change braking for a lead car — that is Lead Braking Assertiveness.")

    return (f"{desc}<br><br><b>{tr('Resulting limit')}</b> — -{limit:.1f} m/s²"
            f"<br><br>{_personality_note(False)}")

  def _follow_distance_description(self) -> str:
    scale = self.follow_distance.action_item.get_value() / 100.0
    stop_distance = self.stop_distance.action_item.get_value()
    v_ref, speed_label = _ref_speed()
    active = _active_personality()

    # gap = t_follow * v + stop_distance. Show every personality so this can be dialled
    # in per personality, with the selected one marked. Time gap (gap / v) is the number
    # that actually says how much room there is, so quote it alongside the distance.
    rows = []
    for value, name, t_follow in _PERSONALITIES:
      gap = t_follow * scale * v_ref + stop_distance
      row = f"{tr(name)}: {_distance(gap)} ({gap / v_ref:.2f} s)"
      rows.append(f"<b>► {row}</b>" if value == active else f"&nbsp;&nbsp;&nbsp;{row}")

    active_t = next((t for value, _, t in _PERSONALITIES if value == active), 1.45)
    time_gap = (active_t * scale * v_ref + stop_distance) / v_ref

    desc = tr("Trims the following distance of whichever personality is selected — 100% is that " +
              "personality's stock headway. The gap is the personality's follow time × your speed, plus " +
              "the Stopping Distance below. Those are the only two terms in the gap, and this is the " +
              "only one of them that scales with speed.")
    header = tr("Gap at {}").format(speed_label)

    if time_gap < 1.0:
      warn = tr("Under a 1.0 second time gap. At this setting openpilot has less room than a person " +
                "needs to react, and its braking authority does not grow to match — the lead braking " +
                "hard is the case that bites. Know what you are choosing here.")
    elif scale < 1.0:
      warn = tr("Below 100% you have less room to the car ahead, and openpilot's braking authority " +
                "does not grow to match. Step down gradually.")
    else:
      warn = ""

    prefix = f"<b>{warn}</b><br><br>" if warn else ""

    return (f"{desc}<br><br>{prefix}<b>{header}</b><br>{'<br>'.join(rows)}"
            f"<br><br>{_personality_note(True)}")

  def _comfort_brake_description(self) -> str:
    percent = self.comfort_brake.action_item.get_value()
    authority = _STOCK_COMFORT_BRAKE * percent / 100.0
    scale = self.follow_distance.action_item.get_value() / 100.0
    stop_distance = self.stop_distance.action_item.get_value()
    v_ref, speed_label = _ref_speed()
    t_follow = next((t for value, _, t in _PERSONALITIES if value == _active_personality()), 1.45)

    # onset = v^2 / (2 * comfort_brake) + t_follow * v + stop_distance
    onset = v_ref ** 2 / (2 * authority) + t_follow * scale * v_ref + stop_distance

    desc = tr("How much braking authority the planner assumes it has when closing on a slower or stopped " +
              "lead. Higher values approach faster and brake later and harder; lower values start braking " +
              "earlier and more gently. This does not change your following distance at steady speed — " +
              "that is Follow Distance and the personality button.")
    warn = tr("Above 100% openpilot leaves itself less room to stop. Raise it one step at a time.")
    onset_label = tr("At {}, starts braking for a stopped car from {}").format(speed_label, _distance(onset))

    prefix = f"<b>{warn}</b><br><br>" if percent > 100 else ""

    return (f"{desc}<br><br>{prefix}<b>{tr('Braking authority')}</b> — {authority:.2f} m/s²"
            f"<br>{onset_label}<br><br>{_personality_note(True)}")

  def _stop_distance_description(self) -> str:
    meters = self.stop_distance.action_item.get_value()

    desc = tr("How far behind a stopped car openpilot comes to rest. Stock is 6 m. It is also added to the " +
              "follow distance at every speed, so it shifts the gap by a fixed amount.")

    return (f"{desc}<br><br><b>{tr('Gap')}</b> — {meters} m ({meters * _M_TO_FT:.0f} ft)"
            f"<br><br>{_personality_note(False)}")
